#!/usr/bin/env python3
"""proof that an emitted IFC reproduces the shipped STEP, part for part: every product of the IFC as the IfcOpenShell
kernel evaluates it (verify.source_props: the pipeline's source reference) against every instance of the shipped STEP
(occstep.delivered_props: the pipeline's delivered reference) - the same ids on both sides, and per part volume, centre
and bounding box within the pipeline's strictest (parametric source) tolerances TOL_SRC_*; the largest deviations are
recorded. usage: prove.py CODE_DIR IFC SHIPPED.step OUT.json [--jobs N]"""
import json, os, sys, tempfile, time, shutil
import numpy as np
code, ifc, step, outp = sys.argv[1:5]
jobs = int(sys.argv[sys.argv.index('--jobs') + 1]) if '--jobs' in sys.argv else 8
sys.path.insert(0, os.path.join(code, 'tools'))
sys.path.insert(0, os.path.join(code, 'kit'))
import verify, occstep
t0 = time.time()
D = occstep.delivered_props(step)
t1 = time.time()
wd = tempfile.mkdtemp(prefix='prove_')
S = verify.source_props(ifc, wd, jobs, keep_log=False)
shutil.rmtree(wd, ignore_errors=True)
t2 = time.time()
ids_d, ids_s = set(D), set(S)
rows, worst = [], dict(vol_rel=0.0, centroid_mm=0.0, bbox_mm=0.0)
bad = []
for pid in sorted(ids_d & ids_s):
    s = S[pid]
    if s.get('v') is None:
        bad.append(dict(part=pid, name=D[pid]['name'], why='source has no closed volume (%s)' % s.get('kind')))
        continue
    dv, dc, db = verify._diff(np.array(s['v']), np.array(s['c']), np.array(s['lo']), np.array(s['hi']), D[pid])
    worst['vol_rel'] = max(worst['vol_rel'], dv); worst['centroid_mm'] = max(worst['centroid_mm'], dc); worst['bbox_mm'] = max(worst['bbox_mm'], db)
    if not (dv <= verify.TOL_SRC_VOL and dc <= verify.TOL_SRC_CEN and db <= verify.TOL_SRC_BBOX):
        bad.append(dict(part=pid, name=D[pid]['name'], vol_rel=dv, centroid_mm=dc, bbox_mm=db))
res = dict(ifc=os.path.basename(ifc), step=os.path.basename(step), step_sha256=occstep.file_sha256(step),
           delivered_parts=len(ids_d), ifc_products_with_geometry=len(ids_s), matched=len(ids_d & ids_s),
           only_in_step=sorted(ids_d - ids_s)[:20], n_only_in_step=len(ids_d - ids_s),
           only_in_ifc=sorted(ids_s - ids_d)[:20], n_only_in_ifc=len(ids_s - ids_d),
           source_kinds=dict(__import__('collections').Counter(v.get('kind') for v in S.values())),
           max_deviation=worst, tolerances=dict(vol_rel=verify.TOL_SRC_VOL, centroid_mm=verify.TOL_SRC_CEN, bbox_mm=verify.TOL_SRC_BBOX),
           failing=bad[:50], n_failing=len(bad), seconds=dict(step=round(t1 - t0, 1), ifc=round(t2 - t1, 1)))
res['reproduced'] = bool(res['matched'] and not res['n_only_in_step'] and not res['n_only_in_ifc'] and not res['n_failing'])
json.dump(res, open(outp, 'w'), indent=1)
print(json.dumps({k: v for k, v in res.items() if k not in ('failing', 'only_in_step', 'only_in_ifc')}))
