#!/usr/bin/env python3
"""reference_defects.csv: for every part verification did not match, whether the evidence points at the reference or
at the rebuild. Both references come from the IfcOpenShell kernel evaluating the IFC (the source B-rep of verify.py
--ifc, and the delivered STEP, written by an IfcOpenShell build too), so a kernel fallback reaches both. Evidence only:
nothing here changes a verification status, and a part without evidence either way stays undetermined.

Evidence against the reference
  kernel_dropped_operands   the kernel's own log for this product (source_kernel_log.jsonl, written by srcbrep.py when
                            verify.py ran): a boolean result it rejected (GEO151 non-manifold) and the retry it then ran
                            with fewer operands than the first attempt - those operands (cuts, openings) are missing
                            from the reference
  source_exceeds_gross      the source volume exceeds the un-voided gross volume of the part's own body extrusions -
                            profile area x extrusion length (schedules), and the kernel's own evaluation of the same
                            uncut IFC extrusion items (--ifc): cuts and openings only remove material, so no shape the
                            IFC defines can have that volume (by more than verify.py's source volume tolerance)
  delivered_exceeds_gross   the same for the delivered STEP's volume (by more than verify.py's delivered tolerance)
  authoring_agrees_rebuild  the authoring tool's own volume of the part (NetVolume, Net volume, Volume) agrees with the
                            rebuild and not with the failing reference
  siblings_agree_rebuild    parts of the same construction (same body profiles and extrusion lengths, same number of
                            cuts and opening solids) whose rebuild matched their source: their source volumes bracket
                            this rebuild and not this part's source
Evidence against the rebuild
  rebuild_failed            INVALID_SOLID, BUILD_ERROR, BUILD_CRASH
  rebuild_exceeds_gross     the rebuild's volume exceeds the gross bound above
  authoring_agrees_reference, siblings_agree_reference   as above, the other way round
Context (no verdict on its own): kernel_repair (the kernel repaired an operand, e.g. GEO188 sewed a non-manifold
first operand), kernel_nonmanifold (a rejected result retried with all operands), kernel_no_operands_left (every cut
judged to leave the volume unchanged, GEO121 / GEO132 - the kernel's own rule, which the rebuild applies too),
references_disagree (the source and the delivered STEP differ from each other), no_source_solid (the kernel's source
B-rep holds no solid: the delivered STEP is the only reference), source_open (the IFC's own surface of the part is not
closed - verify.py's source_check 'source_open': no source volume exists, the delivered STEP is the only reference),
delivered_allowance (the part passes the delivered check only through the delivered file's own deviation from the
source), source_polygons (an exact part's faces, each put on its best-fit plane, and where they came from: the IFC at
full precision or the delivered STEP), authoring_volume / siblings (the figures when they decide nothing), deviation
(each reference's deviation, also relative to the part's size).

The summary also lists every part that matches only because the rebuild reproduces a kernel fallback
(kernel_fallback_matches: the kernel's log has GEO154 'No longer attempting boolean operation with higher fuzziness' -
it gave up on a boolean the IFC states and kept the first operand, as build_solid's rule does, so the rebuild and both
references agree while the IFC's cuts are not applied): such parts are not independently verified.

verdict: reference_defect  evidence against the reference and none against the rebuild
         rebuild_defect    evidence against the rebuild and none against the reference
         undetermined      neither, or both

usage: reference_defects.py SCHEDULE_DIR [--ifc MODEL.ifc]
writes SCHEDULE_DIR/reference_defects.csv and reference_defects_summary.json
"""
import argparse, csv, json, math, os, re, subprocess, sys, tempfile, collections, shutil
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'kit'))
import verify                                                       # noqa: E402  (its tolerances)

FAILED = ('INVALID_SOLID', 'BUILD_ERROR', 'BUILD_CRASH')
# the authoring tool's own volume of a part, first found wins (Tekla BaseQuantities / Tekla Quantity, Revit Dimensions)
AUTH_KEYS = ('BaseQuantities.NetVolume', 'Tekla Quantity.Net volume', 'Tekla Quantity.Volume', 'Dimensions.Volume')
# candidate volume units of an IFC (value x factor = mm3); the one a model uses is read off its matched parts
UNITS = {'mm3': 1.0, 'cm3': 1e3, 'dm3': 1e6, 'm3': 1e9, 'in3': 16387.064, 'ft3': 28316846.592}
_CHECK = re.compile(r'^Operand B (\d+) is (?:non-)?manifold')


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _vec(s):
    return np.array([float(t) for t in s.split()]) if s else None


def _read(folder, name):
    p = os.path.join(folder, name)
    return list(csv.DictReader(open(p, newline='', encoding='utf-8'))) if os.path.exists(p) else []


# ---------------------------------------------------------------------------------------------------- kernel log
def kernel_log(folder):
    """{guid: [log lines in kernel order]} from source_kernel_log.jsonl (None when verify ran without it)"""
    p = os.path.join(folder, 'source_kernel_log.jsonl')
    if not os.path.exists(p):
        return None
    out = collections.defaultdict(list)
    for line in open(p):
        d = json.loads(line)
        if d.get('guid'):
            out[d['guid']].append(d)
    return out


def kernel_events(lines):
    """what the kernel's log says about one product. Every boolean call starts with the kernel checking its operands
    ('Operand B k is manifold', k = 0..n-1); a result it rejects is logged GEO151 and the call is run again - the
    operand count of that next call against the rejected one says whether operands were dropped.
    -> {'calls': [operand count per call], 'nonmanifold': n, 'retries': [(operands of the rejected call, operands of its
    retry)], 'no_operands_left': n, 'unchanged_halfspaces': n, 'repairs': [message], 'failures': [message]}"""
    ev = dict(calls=[], rejected=[], nonmanifold=0, retries=[], no_operands_left=0, unchanged_halfspaces=0, repairs=[],
              failures=[])
    for d in lines:
        code, msg, lv = d.get('code', ''), d.get('message', ''), d.get('level', '')
        m = _CHECK.match(msg)
        if m:
            k = int(m.group(1))
            if k == 0 or not ev['calls']:
                ev['calls'].append(1)
                ev['rejected'].append(False)
            else:
                ev['calls'][-1] = max(ev['calls'][-1], k + 1)
        if code == 'GEO151' or 'non-manifold result' in msg:
            ev['nonmanifold'] += 1
            if ev['rejected']:
                ev['rejected'][-1] = True
        if 'using first operand' in msg:
            ev['no_operands_left'] += 1
        if 'unchanged volume' in msg:
            ev['unchanged_halfspaces'] += 1
        if code == 'GEO188' or 'sewed' in msg.lower():
            ev['repairs'].append(msg)
        if lv == 'error' or ('fail' in msg.lower() and lv in ('warning', 'error')):
            ev['failures'].append(msg)
    for i in range(len(ev['calls']) - 1):
        if ev['rejected'][i] and ev['calls'][i + 1] < ev['calls'][i]:
            ev['retries'].append((ev['calls'][i], ev['calls'][i + 1]))
    return ev


# ---------------------------------------------------------------------------------------------------- gross bound
def schedule_gross(sched):
    """{part_id: un-voided gross volume of its body extrusions (profile area x scale^2 x |vector . profile normal|),
    mm3} for parametric parts built from straight extrusions only"""
    import steelbuild
    area = {}
    out = {}
    paths = getattr(sched, 'paths', {}) or {}
    for p in sched.parts:
        if p.get('geometry') != 'parametric':
            continue
        body = sched.body_of.get(p['part_id'], [])
        if not body or any(sid in paths for sid in body):
            continue
        v = 0.0
        try:
            for sid in body:
                s = sched.solids[sid]
                pid = s['profile_id']
                if pid not in area:
                    area[pid] = steelbuild.profile_face(sched.profiles[pid], sched.outlines.get(pid)).area
                sc = steelbuild._num(s.get('scale'), 1.0)
                z = np.array([steelbuild._num(s['zx']), steelbuild._num(s['zy']), steelbuild._num(s['zz'])])
                z = z / np.linalg.norm(z)
                vec = np.array([steelbuild._num(s['vx']), steelbuild._num(s['vy']), steelbuild._num(s['vz'])])
                v += area[pid] * sc * sc * abs(float(vec @ z))
        except Exception:
            continue
        out[p['part_id']] = v
    return out


def kernel_gross(ifc, guids):
    """{guid: volume (mm3) of the kernel's own evaluation of the product's uncut base extrusions} (srcbrep.py --gross,
    its own process: IfcOpenShell and OCP never share one)"""
    from OCP.BRepTools import BRepTools
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Shape
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    if not guids:
        return {}
    d = tempfile.mkdtemp(prefix='gross_')
    try:
        subprocess.run([sys.executable, os.path.join(HERE, 'srcbrep.py'), ifc, d, '--gross', ','.join(sorted(guids))],
                       check=True, stdout=subprocess.DEVNULL)
        idx = json.load(open(os.path.join(d, 'gross_index.json')))
        out = {}
        for g, files in idx.items():
            if not files or any(not fn.endswith('.brep') for fn in files):
                continue
            v = 0.0
            for fn in files:
                sh = TopoDS_Shape()
                BRepTools.Read_s(sh, os.path.join(d, fn), BRep_Builder())
                ex = TopExp_Explorer(sh, TopAbs_SOLID)
                while ex.More():
                    gp = GProp_GProps()
                    BRepGProp.VolumeProperties_s(ex.Current(), gp)
                    v += gp.Mass() * 1e9
                    ex.Next()
            out[g] = v
        return out
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------------------------------- authoring volume
def authoring_volumes(folder, V):
    """the authoring tool's volume per part in mm3, its unit read off the model's matched parts: (dict, note)"""
    p = os.path.join(folder, 'part_properties.jsonl')
    if not os.path.exists(p):
        return {}, 'no part_properties.jsonl'
    raw = {}
    for line in open(p):
        r = json.loads(line)
        allv = dict(r.get('properties') or {})
        allv.update(r.get('quantities') or {})
        for k in AUTH_KEYS:
            x = _f(allv.get(k))
            if x is not None and x > 0:
                raw[r['part_id']] = (k, x)
                break
    if not raw:
        return {}, 'no authoring volume in the model'
    ratios = [float(V[g]['volume']) / x for g, (k, x) in raw.items()
              if g in V and V[g].get('status') == 'match' and _f(V[g].get('volume'))]
    if len(ratios) < 10:
        return {}, f'authoring volume on {len(raw)} parts, too few matched parts ({len(ratios)}) to read its unit'
    med = float(np.median(ratios))
    unit = min(UNITS, key=lambda u: abs(math.log(med / UNITS[u])))
    f = UNITS[unit]
    if abs(med / f - 1.0) > 0.01:
        return {}, f'authoring volume unit not recognised (median rebuild/value {med:.6g})'
    rel = sorted(abs(r / f - 1.0) for r in ratios)
    p95 = rel[int(0.95 * (len(rel) - 1))]
    keys = collections.Counter(k for k, _ in raw.values())
    note = (f'authoring volume {dict(keys)} in {unit} (median rebuild/value {med / f:.6f} over {len(ratios)} matched '
            f'parts; 95% of them within {p95:.2%})')
    return {g: (k, x * f) for g, (k, x) in raw.items()}, (note, max(verify.TOL_VOL_REL, p95))


# ---------------------------------------------------------------------------------------------------- siblings
def families(sched):
    """construction family of every parametric part: body profiles + extrusion lengths, number of cuts on the body
    solids, number of opening solids"""
    import steelbuild
    fam = {}
    for p in sched.parts:
        if p.get('geometry') != 'parametric':
            continue
        body = sched.body_of.get(p['part_id'], [])
        if not body:
            continue
        sig = []
        for sid in body:
            s = sched.solids[sid]
            L = math.sqrt(sum(steelbuild._num(s[c]) ** 2 for c in ('vx', 'vy', 'vz')))
            sig.append((s['profile_id'], round(L, 2)))
        ncut = sum(len(sched.cuts_of.get(sid, [])) for sid in body)
        nop = sum(len(o['tool_solids'].split()) for o in sched.open_of.get(p['part_id'], []))
        fam[p['part_id']] = (tuple(sorted(sig)), ncut, nop)
    return fam


# ---------------------------------------------------------------------------------------------------- classification
def classify(folder, ifc=None):
    import steelbuild
    rows = _read(folder, 'verification.csv')
    V = {r['part_id']: r for r in rows}
    bad = [r for r in rows if r['status'] != 'match']
    sched = steelbuild.Schedules(folder)
    klog = kernel_log(folder)
    census = {r['part_id']: r for r in _read(folder, 'source_brep_census.csv')}
    faces_src = {r['part_id']: r['faces_source'] for r in _read(folder, 'exact_sources.csv')}
    gross_s = schedule_gross(sched)
    want = [r['part_id'] for r in bad if r['geometry'] == 'parametric']
    gross_k = kernel_gross(ifc, want) if ifc and want else {}
    auth, anote = authoring_volumes(folder, V)
    a_tol = anote[1] if isinstance(anote, tuple) else None
    fam = families(sched)
    members = collections.defaultdict(list)
    for pid, k in fam.items():
        r = V.get(pid)
        if r and r['status'] == 'match' and r.get('source_check') == 'exact' and _f(r.get('s_v')):
            members[k].append(float(r['s_v']))
    out = []
    for r in bad:
        pid = r['part_id']
        ref_ev, reb_ev, ctx = [], [], []
        v, sv, dv = _f(r.get('volume')), _f(r.get('s_v')), _f(r.get('delivered_volume'))
        src_bad, del_bad = r.get('source_check') == 'DIFFERS', r.get('delivered_check') == 'DIFFERS'
        if r['status'] in FAILED:
            reb_ev.append(f"rebuild_failed: {r['status']}" + (f" ({r['invalid_solids']} of {r['n_solids']} solids)" if r['status'] == 'INVALID_SOLID' else f": {r.get('error', '')}"))
        # the kernel's own log
        if klog is None:
            ctx.append('kernel_log: not captured (verify.py ran without srcbrep.py logging)')
        else:
            ev = kernel_events(klog.get(pid, []))
            for a, b in ev['retries']:
                ref_ev.append(f'kernel_dropped_operands: boolean result rejected as non-manifold (GEO151), retried with {b} of {a} operands')
            if ev['nonmanifold'] and not ev['retries']:
                ctx.append(f"kernel_nonmanifold: {ev['nonmanifold']} boolean result(s) rejected as non-manifold (GEO151), retried without dropping operands")
            if ev['no_operands_left']:
                ctx.append(f"kernel_no_operands_left: {ev['no_operands_left']} boolean(s) found every cut leaving the volume unchanged "
                           f"({ev['unchanged_halfspaces']} half space(s), GEO121) or disjoint, and kept the first operand (GEO132)")
            for m in sorted(set(ev['repairs'])):
                ctx.append(f'kernel_repair: {m}')
            for m in sorted(set(ev['failures'])):
                ctx.append(f'kernel_failure: {m}')
        if r.get('source_check') == 'source_open':
            ctx.append(f"source_open: the IFC's own surface of this part is not closed ({r.get('src_open_shells') or '?'} open shell(s), "
                       f"{r.get('src_free_edges') or '?'} free edge(s) after sewing the kernel's faces at the builder's tolerance): no source "
                       f"volume exists - the delivered STEP is the only reference")
        if r.get('delivered_within_allowance_only') == 'yes':
            ctx.append(f"delivered_allowance: the delivered check passes only through the delivered file's own deviation from the source "
                       f"(volume {r.get('delivered_facet_dev_vol_rel')}, centroid {r.get('delivered_facet_dev_centroid_mm')} mm, bbox "
                       f"{r.get('delivered_facet_dev_bbox_mm')} mm)")
        c = census.get(pid)
        if c is not None and r.get('source_check') == 'n/a':
            ctx.append(f"no_source_solid: kernel B-rep holds {c['solids']} solids, {c['shells']} shells, {c['faces']} faces - the delivered STEP is the only reference")
        elif c is None and r.get('source_check') == 'n/a' and census:
            ctx.append('no_source_solid: the kernel produced no B-rep for this product - the delivered STEP is the only reference')
        # gross bound
        gb = [x for x in (gross_s.get(pid), gross_k.get(pid)) if x]
        if gb:
            bound = max(gb)
            desc = ' / '.join(f'{name} {x:,.3f} mm3' for name, x in (('schedule', gross_s.get(pid)), ('kernel', gross_k.get(pid))) if x)
            if sv is not None and sv > bound * (1 + verify.TOL_SRC_VOL):
                ref_ev.append(f'source_exceeds_gross: source volume {sv:,.3f} mm3 exceeds the un-voided gross extrusion ({desc}) by {sv / bound - 1:.2%}')
            if dv is not None and dv > bound * (1 + verify.TOL_VOL_REL):
                ref_ev.append(f'delivered_exceeds_gross: delivered volume {dv:,.3f} mm3 exceeds the un-voided gross extrusion ({desc}) by {dv / bound - 1:.2%}')
            if v is not None and v > bound * (1 + 1e-9):
                reb_ev.append(f'rebuild_exceeds_gross: rebuild volume {v:,.3f} mm3 exceeds the un-voided gross extrusion ({desc})')
        # the authoring tool's own volume
        if pid in auth and v:
            key, A = auth[pid]
            rv = abs(v - A) / A
            fails = [(n, x) for n, x, b in (('source', sv, src_bad), ('delivered', dv, del_bad)) if b and x]
            parts = ', '.join(f'{n} {abs(x - A) / A:.3%}' for n, x in fails)
            if fails and rv <= a_tol and all(abs(x - A) / A > a_tol for _, x in fails):
                ref_ev.append(f'authoring_agrees_rebuild: {key} {A:,.3f} mm3 - rebuild within {rv:.3%}, {parts} (agreement: within {a_tol:.2%})')
            elif fails and rv > a_tol and all(abs(x - A) / A <= a_tol for _, x in fails):
                reb_ev.append(f'authoring_agrees_reference: {key} {A:,.3f} mm3 - rebuild off by {rv:.3%}, {parts} (agreement: within {a_tol:.2%})')
            else:
                ctx.append(f'authoring_volume: {key} {A:,.3f} mm3 - rebuild {rv:.3%}' + (f', {parts}' if parts else ''))
        # siblings of the same construction
        k = fam.get(pid)
        sib = [x for x in members.get(k, [])] if k else []
        if len(sib) >= 3 and v and sv is not None:
            lo, hi = min(sib), max(sib)
            tol = verify.TOL_SRC_VOL * float(np.median(sib))
            inside = lambda x: lo - tol <= x <= hi + tol
            txt = f'{len(sib)} parts of the same construction match their source, source volumes {lo:,.3f}..{hi:,.3f} mm3'
            if inside(v) and not inside(sv):
                ref_ev.append(f'siblings_agree_rebuild: {txt}; rebuild {v:,.3f} inside, source {sv:,.3f} outside')
            elif inside(sv) and not inside(v):
                reb_ev.append(f'siblings_agree_reference: {txt}; source {sv:,.3f} inside, rebuild {v:,.3f} outside')
            else:
                ctx.append(f'siblings: {txt}; rebuild {v:,.3f}, source {sv:,.3f}')
        # an exact part is its source's own polygons, each put on its best-fit plane: how far from planar they are
        if r['geometry'] == 'exact' and pid in sched.exact:
            flat = [steelbuild._flatness(fc, *steelbuild._plane_of(fc)) for so in sched.exact[pid]['solids'] for fc in so['faces']
                    if steelbuild._plane_of(fc)[0] is not None]
            fs = faces_src.get(pid) or ('ifc' if sched.exact[pid].get('source') == 'IFC faceted geometry, full precision' else 'delivered_step')
            whose = "the IFC's own faceted geometry at full precision" if fs == 'ifc' else "the delivered STEP's own polygons (0.01 mm grid)"
            if flat:
                ctx.append(f'source_polygons: {len(flat)} faces built from {whose}, each on its best-fit plane; '
                           f'the least planar is {max(flat):.4f} mm off its plane, {sum(x > steelbuild.SEW_TOL for x in flat)} more than {steelbuild.SEW_TOL} mm')
        # the two references against each other, and the deviation relative to the part's size
        lo_, hi_ = _vec(r.get('lo')), _vec(r.get('hi'))
        size = float(np.linalg.norm(hi_ - lo_)) if lo_ is not None and hi_ is not None else None
        if sv is not None and dv is not None and r.get('d_cx') and r.get('s_cx'):
            sc_ = np.array([float(r[c]) for c in ('s_cx', 's_cy', 's_cz')])
            dc_ = np.array([float(r[c]) for c in ('d_cx', 'd_cy', 'd_cz')])
            fv, fc = abs(sv - dv) / max(abs(dv), 1e-9), float(np.linalg.norm(sc_ - dc_))
            if src_bad and not del_bad:
                ctx.append(f'references_disagree: the source and the delivered STEP differ from each other by volume {fv:.2e}, centroid {fc:.4f} mm; the rebuild matches the delivered STEP')
            elif del_bad and not src_bad:
                ctx.append(f'references_disagree: the source and the delivered STEP differ from each other by volume {fv:.2e}, centroid {fc:.4f} mm; the rebuild matches the source')
        if size:
            dev = []
            for name, cv, cc, cb in (('source', r.get('src_vol_rel_diff'), r.get('src_centroid_diff_mm'), r.get('src_bbox_diff_mm')),
                                     ('delivered', r.get('vol_rel_diff'), r.get('centroid_diff_mm'), r.get('bbox_diff_mm'))):
                if _f(cc) is not None:
                    dev.append(f'{name}: volume {cv}, centroid {float(cc):.4f} mm = {float(cc) / size:.1e} of the part size, bbox {float(cb):.4f} mm = {float(cb) / size:.1e}')
            ctx.append(f'deviation (part size {size:,.1f} mm, bbox diagonal): ' + '; '.join(dev))
        verdict = 'reference_defect' if ref_ev and not reb_ev else 'rebuild_defect' if reb_ev and not ref_ev else 'undetermined'
        out.append(dict(part_id=pid, ifc_class=r['ifc_class'], geometry=r['geometry'], status=r['status'],
                        source_check=r.get('source_check', ''), delivered_check=r.get('delivered_check', ''), verdict=verdict,
                        evidence=' | '.join(ref_ev + reb_ev + ctx), volume=r.get('volume', ''), source_volume=r.get('s_v', ''),
                        delivered_volume=r.get('delivered_volume', ''), gross_schedule=f'{gross_s[pid]:.3f}' if pid in gross_s else '',
                        gross_kernel=f'{gross_k[pid]:.3f}' if pid in gross_k else '',
                        authoring_volume=f'{auth[pid][1]:.3f}' if pid in auth else ''))
    # parts that match only because the rebuild reproduces the kernel giving up on a boolean (GEO154)
    fallback = []
    for pid, lines in sorted((klog or {}).items()):
        if any(d.get('code') == 'GEO154' for d in lines) and pid in V:
            fallback.append(dict(part_id=pid, status=V[pid]['status'], geometry=V[pid]['geometry'],
                                 messages=sorted({f"{d.get('code')}: {d.get('message')}" for d in lines
                                                  if d.get('code') in ('GEO151', 'GEO154')})))
    # parts with a cutting / opening solid the kernel cannot build (steelbuild.kernel_unbuilt: full-round rounded
    # rectangle) - the rebuild leaves it out as the kernel does; listed only where such a tool exists
    unbuilt = []
    try:
        sch = sched
        tools = collections.defaultdict(list)
        for c in sch.cuts:
            if c['kind'] == 'solid' and c['tool_solid_id'] in sch.solids and steelbuild.kernel_unbuilt(sch.solids[c['tool_solid_id']], sch):
                tools[sch.solids[c['solid_id']]['part_id']].append(c['tool_solid_id'])
        for o in sch.openings:
            for tid in o['tool_solids'].split():
                if tid in sch.solids and steelbuild.kernel_unbuilt(sch.solids[tid], sch):
                    tools[o['part_id']].append(tid)
        for pid_, tl in sorted(tools.items()):
            unbuilt.append(dict(part_id=pid_, status=V.get(pid_, {}).get('status', ''), geometry=V.get(pid_, {}).get('geometry', ''),
                                tools_left_out=len(tl), kernel_geo027=any(d.get('code') == 'GEO027' for d in (klog or {}).get(pid_, []))))
    except Exception as e:
        unbuilt = [dict(error=f'{type(e).__name__}: {e}')]
    return out, (anote[0] if isinstance(anote, tuple) else anote), len(rows), klog is not None, fallback, unbuilt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('folder')
    ap.add_argument('--ifc', default='')
    a = ap.parse_args()
    rows, anote, n, logged, fallback, unbuilt = classify(a.folder, a.ifc or None)
    cols = ['part_id', 'ifc_class', 'geometry', 'status', 'source_check', 'delivered_check', 'verdict', 'evidence', 'volume',
            'source_volume', 'delivered_volume', 'gross_schedule', 'gross_kernel', 'authoring_volume']
    with open(os.path.join(a.folder, 'reference_defects.csv'), 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    summ = dict(parts=n, not_matched=len(rows), verdict=dict(collections.Counter(r['verdict'] for r in rows)),
                kernel_log=logged, authoring=anote,
                by_part={r['part_id']: r['verdict'] for r in rows},
                kernel_fallback_matches=[f for f in fallback if f['status'] == 'match'],
                kernel_fallback_note=('parts whose kernel log has GEO154: the kernel gave up on a boolean the IFC states and '
                                      'kept the first operand; build_solid applies the same rule, so a match here means '
                                      'the rebuild agrees with that fallback, not with the cuts the IFC states - not '
                                      'independently verified'),
                kernel_fallback_parts=fallback)
    if unbuilt:
        summ['kernel_unbuilt_tool_parts'] = unbuilt
        summ['kernel_unbuilt_tool_note'] = ('parts with a cutting / opening solid the IfcOpenShell kernel cannot build (a full-round '
                                            'IfcRoundedRectangleProfileDef, GEO027): source and delivered STEP keep that material, the '
                                            'rebuild leaves the tool out as the kernel does (steelbuild.kernel_unbuilt) - a match here '
                                            'agrees with the kernel, not with the cut the IFC states')
    json.dump(summ, open(os.path.join(a.folder, 'reference_defects_summary.json'), 'w'), indent=1)
    print(json.dumps({k: v for k, v in summ.items() if k not in ('by_part', 'kernel_fallback_parts')}))
    for r in rows:
        print(r['part_id'], r['status'], r['verdict'], '::', r['evidence'])


if __name__ == '__main__':
    main()
