#!/usr/bin/env python3
"""Why does v5.3 skip reference-model placements ('reference_part_no_closed_brep')? Per skipped piece: B-rep parse,
face limit, solid / open-shell sewing, absurd size, BRepCheck validity; then the placement frame for shapes that are fine.
usage: ref_causes.py PIPE JOB SKIPPED_CSV OUT_JSON"""
import sys, os, csv, json, struct, collections
import numpy as np
PIPE, job, skipped_csv, out = sys.argv[1:5]
sys.path.insert(0, os.path.join(PIPE, 'decode'))
import brep, to_step2, instances
from OCP.BRepCheck import BRepCheck_Analyzer


def parse_why(b):
    hdr, vrec, lrec, frec, co, marker = brep.LAYOUTS[0]
    if len(b) < hdr + 12:
        return 'short_file'
    nv, nf, ne = struct.unpack('>3I', b[hdr:hdr + 12])
    if not (3 < nv < 200000 and 0 < nf < 100000 and nf <= ne < 1000000):
        return f'counts_out_of_range'
    v0 = hdr + 16
    if v0 + vrec * nv + lrec * ne > len(b):
        return 'truncated_records'
    V = np.array([struct.unpack('>3d', b[v0 + vrec * i:v0 + vrec * i + 24]) for i in range(nv)])
    if not np.isfinite(V).all():
        return 'nonfinite_vertex'
    if np.abs(V).max() > 1e5:
        return 'vertex_beyond_1e5_in'
    return 'face_records_check'


rows = list(csv.DictReader(open(skipped_csv)))
by_reason = collections.Counter(r['reason'] for r in rows)
ref_rows = [r for r in rows if r['reason'] == 'reference_part_no_closed_brep']
sids = collections.Counter(int(r['piece']) for r in ref_rows)
cause = {}
extra = {}
for sid in sids:
    try:
        b = open(os.path.join(job, 'subm', str(sid)), 'rb').read()
    except OSError:
        cause[sid] = 'piece_file_missing'; continue
    try:
        r = brep.parse(b)
    except Exception as e:
        cause[sid] = 'parse_exception'; continue
    if r is None:
        cause[sid] = 'parse_none:' + parse_why(b); continue
    nfa = len(r[1])
    extra[sid] = {'faces': nfa, 'verts': len(r[0])}
    if nfa > to_step2.REF_MAX_FACES:
        cause[sid] = 'faces_over_REF_MAX_FACES'; continue
    try:
        sh = brep.solid(*r); kind = 'solid'
        if sh is None:
            sh = brep.shell(*r); kind = 'open_shell'
    except Exception:
        cause[sid] = 'sew_exception'; continue
    if sh is None:
        cause[sid] = 'no_solid_no_shell'
    elif to_step2._absurd(sh, 1e5):
        cause[sid] = kind + '_absurd_extent'
    elif not BRepCheck_Analyzer(sh).IsValid():
        cause[sid] = kind + '_brepcheck_invalid'
    else:
        cause[sid] = kind + '_shape_ok'
# placement check for shapes that are fine
ok_sids = {s for s, c in cause.items() if c.endswith('_shape_ok')}
plc = collections.Counter()
if ok_sids:
    ids_ = [int(x) for x in os.listdir(os.path.join(job, 'subm')) if x.isdigit()]
    ref_pieces = {i: dict(name='REFERENCE', sec=0, L=0, W=0, T=0, wt=0) for i in ids_}
    members = sorted({int(r['member']) for r in ref_rows})
    for n in members:
        _, rinst = instances.material_instances(job, n, ref_pieces)
        for sid, M, o in rinst:
            if sid in ok_sids:
                plc['placement_none' if to_step2.placement(M, o) is None else 'placement_ok'] += 1
by_pl = collections.Counter()
for r in ref_rows:
    by_pl[cause.get(int(r['piece']), '?')] += 1
res = {'skipped_rows': len(rows), 'skipped_by_reason': dict(by_reason), 'unique_skipped_pieces': len(sids),
       'pieces_by_cause': dict(collections.Counter(cause.values())), 'placements_by_cause': dict(by_pl),
       'shape_ok_placement_check': dict(plc),
       'faces_hist_of_skipped': dict(collections.Counter(min(x['faces'], 50000) // 1000 * 1000 for x in extra.values())),
       'sample': [{'piece': s, 'cause': cause[s], **extra.get(s, {})} for s in list(sids)[:30]]}
json.dump(res, open(out, 'w'), indent=1)
print(json.dumps({k: v for k, v in res.items() if k != 'sample'}))
