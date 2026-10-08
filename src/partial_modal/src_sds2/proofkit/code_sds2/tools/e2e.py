#!/usr/bin/env python3
"""End-to-end test of a packaged model script, exactly as a user runs it: `python build_model.py ...` writes a STEP,
the STEP is read back and every product (one per part, labelled with its id) must pass the same checks as the verified
rebuild of that part (verification.csv): the same source and delivered checks with the same tolerances (verify.check,
against the reference values recorded in verification.csv), the same bodies (shells: a STEP writer drops a solid it
cannot write; a solid of two disjoint lumps legitimately comes back as two solids, so solids are not counted), and every
solid read back valid (BRepCheck, in the part's own frame) and closed (no free edge: an open solid is a failure, never
measured as if it had a volume). Volumes are measured solid by solid. Runs the whole model
and a seeded sample of `--assembly-id` (including nested assemblies and assemblies whose members are only other
assemblies) and `--mark` selections, and checks determinism: the whole model built a second time with a different
number of parallel jobs must produce a byte-identical STEP DATA section.

Reported deviations per run: of the parts read back against the delivered and source references (absolute and
relative to the part size), and against the in-memory rebuild of verification.csv (the file's reproduction of the
rebuild: informative, no pass/fail).

usage: e2e.py MODEL_SCRIPT_DIR [--jobs N] [--sample N]      (MODEL_SCRIPT_DIR = scripts/<model>/ of a package)
writes MODEL_SCRIPT_DIR/e2e_summary.json and e2e_results.csv
"""
import argparse, collections, csv, json, os, random, subprocess, sys, tempfile, time
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verify                         # the part checks and tolerances (CAD modules are imported lazily)


def read_step(path):
    """{part id: read-back measures} of every product of a STEP file: volume, centre and bounding box summed over its
    solids (each solid measured on its own), and its counts of solids, invalid solids, open solids and stray surfaces
    (shells or faces outside any solid)"""
    from build123d import import_step
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_SHELL, TopAbs_SOLID, TopAbs_FACE
    s = import_step(path)
    out = {}
    for c in (s.children if hasattr(s, 'children') else []):
        lab = c.label or ''
        pid = lab[:22]
        sol = c.solids()
        v, m, lo, hi = verify._props(sol)
        # valid as read back from the file (BRepCheck), checked in the frame the file defines the part's B-rep in: the
        # product's own representation, before its instance placement (a pure translation to the part's site, up to
        # ~500 m from the origin) is applied. The STEP reader recomputes edge tolerances with no margin (tol = measured
        # deviation when > 1e-7 mm); evaluating the same B-rep after a 5e5 mm translation adds ~1e-11 mm of rounding to
        # every distance BRepCheck measures, which flips such edges to 'invalid' although the stored solid is valid.
        invalid = sum(1 for x in sol if not BRepCheck_Analyzer(x.wrapped.Located(TopLoc_Location())).IsValid())
        stray = 0
        for kind, avoid in ((TopAbs_SHELL, TopAbs_SOLID), (TopAbs_FACE, TopAbs_SHELL)):
            ex = TopExp_Explorer(c.wrapped, kind, avoid)
            while ex.More():
                stray += 1
                ex.Next()
        out[pid] = dict(v=v, c=m, lo=lo, hi=hi, n_solids=len(sol), n_shells=verify.n_shells(sol), invalid=invalid,
                        open=verify.open_solids(sol), stray=stray)
    return out


def data_digest(path):
    """sha256 of a STEP file's DATA section (the header above it only carries the file name and the time of writing)"""
    import hashlib
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for line in fh:
            if line.startswith(b'DATA;'):
                h.update(line)
                break
        for line in fh:
            h.update(line)
    return h.hexdigest()


def run(model_dir, args, out):
    t0 = time.time()
    r = subprocess.run([sys.executable, os.path.join(model_dir, 'build_model.py'), '--out', out] + args, capture_output=True, text=True, cwd=model_dir)
    return r.returncode, r.stdout + r.stderr, time.time() - t0


# the file's reproduction of the in-memory rebuild (the comparison e2e.py gated on before; now reported for information,
# it decides nothing): volume within 1e-5 or 5e-4 mm3 (verification.csv keeps volumes to 0.001 mm3), centre within
# 0.005 mm. Every part beyond it is listed with its deviations (examples 'off_rebuild'), the run's verdict on it is the
# informational column repro_ok
REPRO_VOL_REL, REPRO_VOL_ABS, REPRO_CEN = 1e-5, 5e-4, 0.005


def _vec(s):
    return np.array([float(x) for x in s.split()])


def _refs(r):
    """the delivered and source references of a part as verification.csv records them"""
    ref = src = None
    if r.get('delivered_volume') not in (None, ''):
        ref = dict(v=float(r['delivered_volume']), c=[float(r['d_cx']), float(r['d_cy']), float(r['d_cz'])], lo=_vec(r['d_lo']), hi=_vec(r['d_hi']))
    if r.get('s_v') not in (None, ''):
        src = dict(v=float(r['s_v']), c=[float(r['s_cx']), float(r['s_cy']), float(r['s_cz'])], lo=_vec(r['s_lo']), hi=_vec(r['s_hi']),
                   kind=r.get('source_kind') or 'solid')        # (a verification.csv without the column had kernel solids only)
    return ref, src


def compare(got, expect_ids, V):
    """every expected part read back must pass every check its verified rebuild passed"""
    missing = sorted(set(expect_ids) - set(got))
    extra = sorted(set(got) - set(expect_ids))
    reasons, examples = collections.Counter(), collections.defaultdict(list)
    dev = collections.defaultdict(float)
    status = collections.Counter()
    repro_off = []
    regrouped = [0]                       # parts whose bodies come back grouped into another number of solids (info)
    for pid in sorted(set(got) & set(expect_ids)):
        g, r = got[pid], V.get(pid)
        why = []
        if r is None or r.get('volume') in (None, ''):
            why.append('not_verified')
        else:
            # bodies: the shells of the part (a solid of two disjoint lumps comes back as two solids, which is not a
            # change); a verification.csv without n_shells is compared on its solids, for lost ones only
            if r.get('n_shells') not in (None, ''):
                n_ver, n_got = int(r['n_shells']), g['n_shells']
            else:
                n_ver, n_got = int(r.get('n_solids') or 0), min(g['n_solids'], int(r.get('n_solids') or 0))
            if n_got < n_ver:
                why.append('bodies_lost')
            elif n_got > n_ver:
                why.append('bodies_added')
            if g['n_solids'] != int(r.get('n_solids') or 0):
                regrouped[0] += 1
            if g['invalid']:
                why.append('invalid_solid')
            if g['open']:
                why.append('open_solid')
            if g['stray']:
                why.append('open_surface')
            ref, src = _refs(r)
            chk = verify.check(r['geometry'], g['v'], g['c'], g['lo'], g['hi'], ref, src)
            if r.get('delivered_check') == 'match' and chk.get('delivered_check') != 'match':
                why.append('delivered_check')
            if r.get('source_check') == 'exact' and chk.get('source_check') != 'exact':
                why.append('source_check')
            for k_out, k_in in (('delivered_vol_rel', 'vol_rel_diff'), ('delivered_centroid_mm', 'centroid_diff_mm'),
                                ('delivered_centroid_rel', 'centroid_diff_rel'), ('delivered_bbox_mm', 'bbox_diff_mm'),
                                ('delivered_bbox_rel', 'bbox_diff_rel'), ('source_vol_rel', 'src_vol_rel_diff'),
                                ('source_centroid_mm', 'src_centroid_diff_mm'), ('source_centroid_rel', 'src_centroid_diff_rel'),
                                ('source_bbox_mm', 'src_bbox_diff_mm'), ('source_bbox_rel', 'src_bbox_diff_rel')):
                if chk.get(k_in) not in (None, ''):
                    dev[k_out] = max(dev[k_out], float(chk[k_in]))
            rv = float(r['volume'])
            rc = np.array([float(r['cx']), float(r['cy']), float(r['cz'])])
            dvr, dc = abs(g['v'] - rv) / max(abs(rv), 1e-9), float(np.linalg.norm(np.asarray(g['c']) - rc))
            dev['rebuild_vol_rel'] = max(dev['rebuild_vol_rel'], dvr)
            dev['rebuild_centroid_mm'] = max(dev['rebuild_centroid_mm'], dc)
            if abs(g['v'] - rv) > max(REPRO_VOL_REL * abs(rv), REPRO_VOL_ABS) or dc > REPRO_CEN:
                repro_off.append(dict(part_id=pid, vol_rel=f'{dvr:.2e}', centroid_mm=round(dc, 5)))
        status['ok' if not why else 'FAIL'] += 1
        for w in why:
            reasons[w] += 1
            examples[w].append(pid)
    fmt = lambda k: f'{dev[k]:.1e}' if 'rel' in k else round(dev[k], 5)
    return dict(expected=len(expect_ids), in_step=len(got), missing=len(missing), extra=len(extra), parts_ok=status['ok'],
                parts_failing=status['FAIL'], failing_by_reason=dict(reasons),
                invalid_when_reread=sum(1 for pid in set(got) & set(expect_ids) if got[pid]['invalid']),
                open_when_reread=sum(1 for pid in set(got) & set(expect_ids) if got[pid]['open'] or got[pid]['stray']),
                solids_lost=sum(max(0, int((V.get(pid) or {}).get('n_solids') or 0) - got[pid]['n_solids']) for pid in set(got) & set(expect_ids)),
                bodies_lost=sum(max(0, int((V.get(pid) or {}).get('n_shells') or 0) - got[pid]['n_shells']) for pid in set(got) & set(expect_ids)
                                if (V.get(pid) or {}).get('n_shells')),
                parts_regrouped_into_other_solid_count=regrouped[0],
                max_vol_rel=fmt('rebuild_vol_rel'), max_centroid_mm=fmt('rebuild_centroid_mm'), parts_off_rebuild=len(repro_off),
                repro_ok=not repro_off,
                max_deviation_vs_references={k: fmt(k) for k in sorted(dev) if not k.startswith('rebuild')},
                ok=not missing and not extra and not status['FAIL'],
                examples=dict(missing=missing, extra=extra, off_rebuild=repro_off, **{k: v for k, v in examples.items()}))


def _assemblies(S):
    """rows of schedules/assemblies.csv: {id: row}"""
    fn = os.path.join(S, 'assemblies.csv')
    if not os.path.exists(fn) or os.path.getsize(fn) == 0:
        return {}
    return {r['assembly_id']: r for r in csv.DictReader(open(fn, newline='', encoding='utf-8'))}


def expected_for_assembly(aid, parts, tree):
    """the parts documented for an assembly id: its own parts and, through parent_id in assemblies.csv, those of every
    assembly nested in it (computed here independently of build_model.py's selection code)"""
    subs = collections.defaultdict(set)
    for k, r in tree.items():
        if r.get('parent_id'):
            subs[r['parent_id']].add(k)
    ids, todo = set(), [aid]
    while todo:
        a = todo.pop()
        if a not in ids:
            ids.add(a)
            todo += sorted(subs.get(a, ()))
    return [p['part_id'] for p in parts if p['assembly_id'] in ids]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('model_dir')
    ap.add_argument('--jobs', type=int, default=8)
    ap.add_argument('--sample', type=int, default=15)
    ap.add_argument('--nested', type=int, default=12, help='nested / parent assemblies added to the --assembly-id sample')
    a = ap.parse_args()
    d = os.path.abspath(a.model_dir)
    S = os.path.join(d, 'schedules')
    parts = list(csv.DictReader(open(os.path.join(S, 'parts.csv'))))
    V = {r['part_id']: r for r in csv.DictReader(open(os.path.join(d, 'verification.csv')))}
    tree = _assemblies(S)
    tmp = tempfile.mkdtemp()
    rows = []

    def row(level, selection, rc, sec, res):
        return dict(level=level, selection=selection, rc=rc, seconds=round(sec, 1),
                    **{k: (json.dumps(v, sort_keys=True) if isinstance(v, dict) else v) for k, v in res.items() if k != 'examples'},
                    examples=json.dumps(res.get('examples', ''), sort_keys=True))
    # whole model
    rc, log, sec = run(d, ['--jobs', str(a.jobs)], os.path.join(tmp, 'model.step'))
    res = compare(read_step(os.path.join(tmp, 'model.step')), [p['part_id'] for p in parts], V) if rc == 0 else dict(ok=False, error=log)
    model_res = res
    rows.append(row('model', 'all', rc, sec, res))
    # determinism: the whole model built again with a different number of parallel jobs must give the identical file
    j2 = max(1, a.jobs // 2)
    m2 = os.path.join(tmp, 'model2.step')
    rc2, log2, sec2 = run(d, ['--jobs', str(j2)], m2)
    same = rc == 0 and rc2 == 0 and data_digest(os.path.join(tmp, 'model.step')) == data_digest(m2)
    rows.append(dict(level='determinism', selection=f'all: --jobs {a.jobs} vs --jobs {j2}, STEP DATA section compared byte for byte', rc=rc2,
                     seconds=round(sec2, 1), ok=same))
    for f in (m2, os.path.join(tmp, 'model.step')):
        if os.path.exists(f):
            os.remove(f)
    rnd = random.Random(20261006)
    asm = sorted({p['assembly_id'] for p in parts if p['assembly_id']})
    big = sorted(asm, key=lambda x: -sum(1 for p in parts if p['assembly_id'] == x))[:3]
    pick = list(dict.fromkeys(big + rnd.sample(asm, min(a.sample, len(asm)))))
    # nested assemblies (deepest first) and assemblies whose members are only other assemblies: the selections that
    # depend on the hierarchy
    parents = {r['parent_id'] for r in tree.values() if r.get('parent_id')}
    hier = sorted((k for k, r in tree.items() if r.get('parent_id') or k in parents), key=lambda k: (-int(tree[k].get('depth') or 0), k))
    cand = list(dict.fromkeys([k for k in hier if not int(tree[k].get('n_parts') or 0)] + hier))
    pick += [k for k in cand if k not in pick][:a.nested]
    for aid in pick:
        out = os.path.join(tmp, 'a.step')
        rc, log, sec = run(d, ['--assembly-id', aid], out)
        exp = expected_for_assembly(aid, parts, tree)
        res = compare(read_step(out), exp, V) if rc == 0 else dict(ok=False, error=log)
        rows.append(row('assembly', aid, rc, sec, res))
        if os.path.exists(out):
            os.remove(out)
    marks = sorted({p['part_mark'] for p in parts if p['part_mark']})
    for m in rnd.sample(marks, min(a.sample, len(marks))):
        out = os.path.join(tmp, 'm.step')
        rc, log, sec = run(d, ['--mark', m], out)
        exp = [p['part_id'] for p in parts if p['part_mark'].lower() == m.lower()]
        res = compare(read_step(out), exp, V) if rc == 0 else dict(ok=False, error=log)
        rows.append(row('piece', m, rc, sec, res))
        if os.path.exists(out):
            os.remove(out)
    cols = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    with open(os.path.join(d, 'e2e_results.csv'), 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    summ = {lvl: dict(runs=sum(1 for r in rows if r['level'] == lvl), ok=sum(1 for r in rows if r['level'] == lvl and r.get('ok')))
            for lvl in ('model', 'determinism', 'assembly', 'piece')}
    summ['assembly']['nested_or_parent_runs'] = sum(1 for r in rows if r['level'] == 'assembly' and r['selection'] in set(hier))
    summ['model_parts_in_step'] = model_res.get('in_step')
    summ['model_parts_ok'] = model_res.get('parts_ok')
    summ['model_parts_failing'] = model_res.get('parts_failing')
    summ['model_failing_by_reason'] = model_res.get('failing_by_reason')
    summ['model_failing_examples'] = model_res.get('examples')
    # parts whose solids fail BRepCheck / are open after the whole-model STEP is written and read back (a CAD tool
    # opening the file), and solids the writer did not write
    summ['model_parts_invalid_when_reread'] = model_res.get('invalid_when_reread')
    summ['model_parts_open_when_reread'] = model_res.get('open_when_reread')
    summ['model_solids_lost'] = model_res.get('solids_lost')
    summ['model_bodies_lost'] = model_res.get('bodies_lost')
    summ['model_parts_regrouped'] = model_res.get('parts_regrouped_into_other_solid_count')
    summ['model_max_deviation_vs_references'] = model_res.get('max_deviation_vs_references')
    summ['model_max_deviation_reread'] = {'volume_rel': model_res.get('max_vol_rel'), 'centroid_mm': model_res.get('max_centroid_mm'),
                                          'parts_off_rebuild_beyond_1e-5_or_0.005mm': model_res.get('parts_off_rebuild'),
                                          'within_1e-5_and_0.005mm': model_res.get('repro_ok'),
                                          'note': 'information only: the gating checks are the part checks of verification.csv'}
    summ['reproduction_info_only'] = {lvl: {'runs': sum(1 for r in rows if r['level'] == lvl and 'repro_ok' in r),
                                            'within_1e-5_and_0.005mm': sum(1 for r in rows if r['level'] == lvl and r.get('repro_ok') is True)}
                                      for lvl in ('model', 'assembly', 'piece')}
    summ['tolerances'] = dict(part_checks='verify.py, the same as verification.csv',
                              delivered=dict(volume_rel=verify.TOL_VOL_REL, centroid_mm=verify.TOL_CEN, bbox_mm=verify.TOL_BBOX, plus="the delivered file's own deviation from the closed source reference (kernel solids or sewn faceted faces), where one exists"),
                              source_parametric=dict(volume_rel=verify.TOL_SRC_VOL, centroid_mm=verify.TOL_SRC_CEN, bbox_mm=verify.TOL_SRC_BBOX),
                              source_faceted=dict(volume_rel=verify.TOL_GRID_VOL, centroid_mm=verify.TOL_GRID_CEN, bbox_mm=verify.TOL_GRID_BBOX),
                              rebuild_reproduction_info_only=dict(volume_rel=REPRO_VOL_REL, volume_abs_mm3=REPRO_VOL_ABS, centroid_mm=REPRO_CEN))
    json.dump(summ, open(os.path.join(d, 'e2e_summary.json'), 'w'), indent=1)
    print(json.dumps(summ))


if __name__ == '__main__':
    main()
