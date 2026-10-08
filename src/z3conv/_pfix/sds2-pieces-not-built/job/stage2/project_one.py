#!/usr/bin/env python3
"""project_one.py DECODE_DIR JOB SKIPPED_CSV OUT.json [MAX_SIDS] -> replay, per skipped piece, what this converter tree does
with it (built exact / approx / open surface / precise source reason / still skipped). Used for v5.5.3 vs v5.5.3 + patch."""
import sys, os, json, csv, collections, re
sys.path.insert(0, sys.argv[1])
import numpy as np
import to_step2 as T2, brep
from piece_table import read_pieces, kind
from sds2job import read_shapes, REFERENCE_TYPES
from instances import piece_vertices, subm_vertices
job, skp, outp = sys.argv[2], sys.argv[3], sys.argv[4]
MAXS = int(sys.argv[5]) if len(sys.argv) > 5 else 1500
PATCHED = hasattr(T2, '_table_without_size')
rows = list(csv.DictReader(open(skp)))
by = collections.defaultdict(list)
for r in rows:
    try: by[int(r['piece'])].append(r)
    except ValueError: pass
try: pieces = read_pieces(job)
except Exception: pieces = {}
try: shapes = read_shapes(job)
except Exception: shapes = {}
T2.SHARED = True
M = np.eye(3); o = np.zeros(3)
res = []
order = sorted(by, key=lambda s: -len(by[s]))
for n_, sid in enumerate(order):
    rs = by[sid]; r0 = rs[0]; reason = r0['reason']
    d = dict(sid=sid, n=len(rs), name=r0['name'], reason=reason, mtype=r0.get('member_type'), sampled=n_ < MAXS)
    if n_ >= MAXS:
        res.append(d); continue
    out = None
    try:
        if reason.startswith('reference') or r0.get('member_type') in REFERENCE_TYPES or r0.get('kind') == 'reference':
            sh = T2.brep_reference(job, sid, M, o)
            if sh is not None:
                out = 'ref_face_set' if (job, sid) in getattr(T2, 'REF_FACES', set()) else 'ref_open_shell' if (job, sid) in T2.REF_OPEN else 'ref_solid'
            else:
                g = getattr(T2, '_REF_GAP', {}).get((job, sid))
                out = g[0] if g else ('reference_time_budget_exceeded' if reason == 'reference_time_budget_exceeded' else 'reference_part_no_closed_brep')
        else:
            p = pieces.get(sid)
            if p is None:
                out = 'piece_not_in_table'
            elif reason in ('no_usable_special_geometry', 'absurd_extent_corrupt_source_geometry'):
                k = kind(p)
                sh, k2 = T2.special_solid(job, sid, p, M, o)
                b = 'special'
                if sh is None and not p['name'].startswith('Conc'):
                    sh = T2.brep_placed(job, sid, p, M, o); b = 'exact'
                if sh is None and k in ('plate', 'other'):
                    V = piece_vertices(job, sid) if k == 'plate' else subm_vertices(job, sid)
                    sh = T2._place(T2.table_standin(V, p, None), M, o); b = 'table_standin'
                if sh is not None:
                    out = 'absurd' if T2._absurd(sh) else ('built_exact' if b == 'exact' else f'built_{b}' + ('_guess' if T2.SPECIAL_NOTE else ''))
                else:
                    out = T2.skip_reason_for(job, sid, p, 'no_usable_special_geometry') if PATCHED else 'no_usable_special_geometry'
            elif reason == 'fallback_over_5x_source_weight':
                sh = T2.brep_placed(job, sid, p, M, o)
                if sh is not None:
                    out = 'built_exact'
                else:
                    out = 'fallback_over_5x_source_weight'
                    k = kind(p); s_ = shapes.get(p.get('sec')) if k == 'rolled' else None
                    if PATCHED and s_ is not None and (s_.weight or 0) > 0 and p.get('L', 0) > 0:
                        V = piece_vertices(job, sid)
                        if V is not None and len(V) >= 2 and abs(float(np.ptp(V[:, 0])) - p['L']) <= 0.02 * p['L'] + 0.05:
                            out = 'built_approx_2g'
            elif reason == 'fallback_builder_failed':
                out = T2.skip_reason_for(job, sid, p, reason) if PATCHED else reason
            else:
                out = reason
    except Exception as e:
        out = f'error {type(e).__name__}: {str(e)[:80]}'
    d['out'] = out
    res.append(d)
json.dump(dict(job=os.path.basename(job), patched=PATCHED, pieces=res), open(outp, 'w'))
print(os.path.basename(job), len(res))
