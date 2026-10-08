#!/usr/bin/env python3
"""Checks of a COMPLETED scripts tree (runs where build123d is: Modal stage `complete`), folding the results into
schedules/completion.json:

  * every part of the completed schedules built with the shipped steelbuild: valid closed solids, else MAGENTA;
  * untouched parts (schedule rows identical to the baseline) built from schedules_original/ and schedules/: volume and
    bounding box identical (nothing previously correct changed);
  * ops with a `target` (volume / bbox): built part within tolerance, else MAGENTA;
  * add_cuts / replace_cuts: the cut part differs from the baseline part (a cut that removes nothing -> MAGENTA);
  * bbox (mm) per changed part from the build (CHANGES.md coordinates).

    python verify_completed.py --tree scripts/<model> --jobs 16
"""
import argparse
import collections
import json
import math
import os
import sys
import time

INTEG = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, INTEG)
import completion_core as cc          # noqa: E402


def _metrics_chunk(args):
    folder, ids = args
    import steelbuild as sb
    sched = sb.Schedules(folder)
    by = {p['part_id']: p for p in sched.parts}
    out = []
    for pid in ids:
        try:
            solids = sb.build_part(by[pid], sched)
            if not solids:
                out.append((pid, dict(ok=False, error='built no solid')))
                continue
            vol, lo, hi, defects = 0.0, [1e30] * 3, [-1e30] * 3, []
            for k, s in enumerate(solids):
                vol += sb._volume(s.wrapped)
                bb = s.bounding_box()
                lo = [min(lo[0], bb.min.X), min(lo[1], bb.min.Y), min(lo[2], bb.min.Z)]
                hi = [max(hi[0], bb.max.X), max(hi[1], bb.max.Y), max(hi[2], bb.max.Z)]
                d = sb.solid_defects(s)
                if d:
                    defects.append(f'solid {k + 1}: {d}')
            out.append((pid, dict(ok=True, n=len(solids), volume=vol, bbox=[round(v, 4) for v in lo + hi],
                                  defects=defects)))
        except Exception as e:                              # noqa: BLE001 - recorded, never hidden
            out.append((pid, dict(ok=False, error=f'{type(e).__name__}: {e}'[:300])))
    return out


def metrics(folder, ids, jobs):
    res = {}
    if not ids:
        return res
    if jobs > 1 and len(ids) > 20:
        from concurrent.futures import ProcessPoolExecutor
        n = max(1, len(ids) // (jobs * 6))
        chunks = [(folder, ids[i:i + n]) for i in range(0, len(ids), n)]
        with ProcessPoolExecutor(jobs) as ex:
            for r in ex.map(_metrics_chunk, chunks):
                res.update(dict(r))
    else:
        res.update(dict(_metrics_chunk((folder, ids))))
    return res


def same(a, b, rel=1e-9, mm=1e-6):
    if not (a and b and a.get('ok') and b.get('ok')):
        return False
    if a['n'] != b['n']:
        return False
    if abs(a['volume'] - b['volume']) > rel * max(1.0, abs(b['volume'])):
        return False
    return all(abs(x - y) <= mm for x, y in zip(a['bbox'], b['bbox']))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tree', required=True, help='scripts/<model_folder> of the completed model')
    ap.add_argument('--jobs', type=int, default=os.cpu_count() or 1)
    a = ap.parse_args()
    tree = os.path.abspath(a.tree)
    sys.path.insert(0, os.path.dirname(tree))                    # steelbuild.py of the scripts folder
    t0 = time.time()
    sc, so = os.path.join(tree, 'schedules'), os.path.join(tree, 'schedules_original')
    comp = json.load(open(os.path.join(sc, 'completion.json'), encoding='utf-8'))
    _, parts_c = cc.read_csv(os.path.join(sc, 'parts.csv'))
    _, parts_o = cc.read_csv(os.path.join(so, 'parts.csv'))
    ids_c = [p['part_id'] for p in parts_c]
    entries = comp['parts']
    base_ids = {p['part_id'] for p in parts_o}
    mc = metrics(sc, ids_c, a.jobs)
    print(f'built completed: {len(mc)} parts ({time.time() - t0:.0f} s)', flush=True)
    # the baseline build of every baseline part still present (untouched check + cut-effect check)
    mo = metrics(so, [pid for pid in ids_c if pid in base_ids], a.jobs)
    print(f'built baseline: {len(mo)} parts ({time.time() - t0:.0f} s)', flush=True)

    checks = collections.Counter()
    untouched_bad, problems = [], []

    def flag(pid, what, check):
        e = entries.get(pid)
        if e is None:
            p = next(x for x in parts_c if x['part_id'] == pid)
            e = entries[pid] = collections.OrderedDict(colour='GREY', status='unchanged', name=p['name'], ops=[],
                                                       tracks=[], colours=[], provenance=[], resolves=[], where='',
                                                       bbox=None, target=None, kind=[])
        e['colours'].append('MAGENTA')
        e['provenance'].append({'what': what, 'track': 'integrate', 'op': 'check:' + check, 'colour': 'MAGENTA'})
        problems.append({'part_id': pid, 'check': check, 'what': what})

    for pid in ids_c:
        m = mc.get(pid) or {}
        e = entries.get(pid)
        if not m.get('ok'):
            checks['build_failed'] += 1
            flag(pid, f"our script does not build it: {m.get('error')}", 'build_failed')
            continue
        if m['defects'] and not (e and 'MAGENTA' in e.get('colours', [])):
            checks['invalid_or_open'] += 1
            flag(pid, 'our rebuild gives an invalid / open solid: ' + '; '.join(m['defects'])[:200], 'invalid_solid')
        if e and m.get('bbox'):
            e['bbox'] = [round(v, 1) for v in m['bbox']]
        if pid in base_ids and not (set((e or {}).get('kind') or []) & {'replace_part', 'add_cuts', 'replace_cuts'}):
            if same(m, mo.get(pid)):
                checks['untouched_identical'] += 1
            else:
                checks['untouched_differs'] += 1
                untouched_bad.append(pid)
                flag(pid, 'untouched part builds differently from the baseline', 'untouched_differs')
        if e and set(e.get('kind') or []) & {'add_cuts', 'replace_cuts'} and pid in mo:
            if same(m, mo.get(pid)):
                checks['cut_no_effect'] += 1
                flag(pid, 'the added / replaced cuts change nothing in the built part', 'cut_no_effect')
            else:
                checks['cut_effective'] += 1
        tg = (e or {}).get('target')
        if tg:
            rel = float(tg.get('tol_rel', 0.005))
            tmm = float(tg.get('tol_mm', 0.5))
            bad = []
            if tg.get('volume_mm3') is not None and abs(m['volume'] - float(tg['volume_mm3'])) > rel * float(tg['volume_mm3']):
                bad.append(f"volume {m['volume']:.0f} vs target {float(tg['volume_mm3']):.0f} mm3")
            if tg.get('bbox') and any(abs(x - float(y)) > tmm for x, y in zip(m['bbox'], tg['bbox'])):
                bad.append('bbox off the target by > %.1f mm' % tmm)
            if bad:
                checks['target_failed'] += 1
                flag(pid, 'rebuild differs from the target geometry: ' + '; '.join(bad), 'target')
            else:
                checks['target_ok'] += 1
    # colours / labels / counts again (the MAGENTA flags above)
    for pid, e in entries.items():
        cols = set(e['colours'])
        e['colour'] = 'GREY' if (e['status'] == 'accepted' and not cols) else (cc.weakest(cols) if cols else 'GREY')
        pv = [x for x in e['provenance'] if x.get('colour') == e['colour']] or e['provenance']
        what = '; '.join(dict.fromkeys(str(x.get('what', '')) for x in pv))
        basis = '; '.join(dict.fromkeys(cc.short_basis(x, e['colour']) for x in pv if cc.short_basis(x, e['colour'])))
        e['summary'] = cc.ascii_text(f'{what} [{basis}]' if basis else what, 600)
        p = next((x for x in parts_c if x['part_id'] == pid), None)
        if p:
            e['label'] = cc.label_for(e['colour'], e['summary'], f"{pid} {p['name']}".strip())
    cnt = collections.Counter((entries.get(pid) or {}).get('colour', 'GREY') for pid in ids_c)
    comp['counts'] = {c: cnt.get(c, 0) for c in cc.COLOURS}
    vol = lambda ms: sum(m['volume'] for m in ms.values() if m.get('ok'))
    comp['build'] = dict(
        checks=dict(checks), problems=problems[:500], untouched_differs=untouched_bad[:100],
        parts_built=sum(1 for m in mc.values() if m.get('ok')), parts=len(ids_c),
        invalid_or_open=sum(1 for m in mc.values() if m.get('ok') and m['defects']),
        volume_mm3=dict(completed=round(vol(mc), 1), baseline=round(vol(mo), 1)),
        seconds=round(time.time() - t0, 1))
    comp['parts'] = collections.OrderedDict((k, v) for k, v in entries.items())
    json.dump(comp, open(os.path.join(sc, 'completion.json'), 'w', encoding='utf-8'), indent=1)
    print(json.dumps({'counts': comp['counts'], 'checks': dict(checks)}), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
