#!/usr/bin/env python3
"""Per-instance-label proof that an emitted IFC reproduces the shipped STEP (runs in the pipeline env: python 3.11,
build123d / OCP / ifcopenshell 0.9.0 of the fleet requirements, with the pipeline's code_sds2 tools).

Extends nonifc/sds2_emitter/prove.py (same references, same tolerances, same verdict rule) with the full per-instance
table and a name check:
  delivered side   every top-level instance of the shipped STEP with solids, measured on its exact B-rep by
                   OpenCASCADE (occstep.delivered_props: the pipeline's delivered reference); id = sds2label.guid of
                   (sha256 of the shipped STEP, instance label, repeat number)
  source side      every IFC product as the IfcOpenShell kernel evaluates it (verify.source_props: the pipeline's source
                   reference)
  name check       the IFC product's Name (read with ifcopenshell) must equal the STEP instance label of the same id
For every id: in which file it is, volume / centre / bbox deviation, pass at the pipeline's strictest tolerances
TOL_SRC_* (volume 1e-3 relative, centre and bbox 0.05 mm). reproduced = same id set on both sides, no failing part, no
name mismatch.
usage: prove_labels.py CODE_DIR IFC SHIPPED.step OUT_PREFIX [--jobs N]
       writes OUT_PREFIX.json (summary) and OUT_PREFIX.csv.gz (one row per id, sorted by label then id)"""
import csv, gzip, io, json, os, sys, tempfile, time, shutil, collections
import numpy as np
code, ifc, step, outp = sys.argv[1:5]
jobs = int(sys.argv[sys.argv.index('--jobs') + 1]) if '--jobs' in sys.argv else 8
sys.path.insert(0, os.path.join(code, 'tools'))
sys.path.insert(0, os.path.join(code, 'kit'))
import verify, occstep  # noqa: E402
import ifcopenshell  # noqa: E402

t0 = time.time()
D = occstep.delivered_props(step)
t1 = time.time()
wd = tempfile.mkdtemp(prefix='prove_')
S = verify.source_props(ifc, wd, jobs, keep_log=False)
shutil.rmtree(wd, ignore_errors=True)
t2 = time.time()
f = ifcopenshell.open(ifc)
names = {}
for p in f.by_type('IfcProduct'):
    if getattr(p, 'Representation', None) is not None:
        names[p.GlobalId] = p.Name
ifc_schema = f.schema
del f
ids_d, ids_s = set(D), set(S)
rows, worst = [], dict(vol_rel=0.0, centroid_mm=0.0, bbox_mm=0.0)
bad, name_bad = [], []
for pid in sorted(ids_d | ids_s | set(names)):
    d, s = D.get(pid), S.get(pid)
    label = d['name'] if d else names.get(pid)
    r = dict(guid=pid, label=label, in_step=d is not None, in_ifc=s is not None, ifc_name=names.get(pid),
             source_kind=(s or {}).get('kind'), vol_rel='', centroid_mm='', bbox_mm='', ok=False, why='')
    if d is None or s is None:
        r['why'] = 'only in IFC' if d is None else 'only in STEP'
    elif s.get('v') is None:
        r['why'] = 'source has no closed volume (%s)' % s.get('kind')
        bad.append(dict(part=pid, name=label, why=r['why']))
    else:
        dv, dc, db = verify._diff(np.array(s['v']), np.array(s['c']), np.array(s['lo']), np.array(s['hi']), d)
        worst['vol_rel'] = max(worst['vol_rel'], dv)
        worst['centroid_mm'] = max(worst['centroid_mm'], dc)
        worst['bbox_mm'] = max(worst['bbox_mm'], db)
        r.update(vol_rel='%.3e' % dv, centroid_mm='%.3e' % dc, bbox_mm='%.3e' % db)
        if not (dv <= verify.TOL_SRC_VOL and dc <= verify.TOL_SRC_CEN and db <= verify.TOL_SRC_BBOX):
            r['why'] = 'outside TOL_SRC'
            bad.append(dict(part=pid, name=label, vol_rel=dv, centroid_mm=dc, bbox_mm=db))
        elif d['name'] != names.get(pid):
            r['why'] = 'IFC Name differs from the STEP instance label'
            name_bad.append(dict(part=pid, step_label=d['name'], ifc_name=names.get(pid)))
        else:
            r['ok'] = True
    rows.append(r)
rows.sort(key=lambda r: ((r['label'] or ''), r['guid']))
buf = io.StringIO()
cw = csv.DictWriter(buf, fieldnames=list(rows[0].keys()) if rows else ['guid'], lineterminator='\n')
cw.writeheader()
cw.writerows(rows)
with open(outp + '.csv.gz', 'wb') as fh:
    with gzip.GzipFile(fileobj=fh, mode='wb', mtime=0, filename='') as gz:      # deterministic gzip header
        gz.write(buf.getvalue().encode('utf-8'))
res = dict(ifc=os.path.basename(ifc), step=os.path.basename(step), step_sha256=occstep.file_sha256(step), ifc_schema=ifc_schema,
           delivered_parts=len(ids_d), ifc_products_with_geometry=len(ids_s), ifc_products_named=len(names),
           matched=len(ids_d & ids_s), n_only_in_step=len(ids_d - ids_s), only_in_step=sorted(ids_d - ids_s)[:20],
           n_only_in_ifc=len(ids_s - ids_d), only_in_ifc=sorted(ids_s - ids_d)[:20],
           source_kinds=dict(collections.Counter(v.get('kind') for v in S.values())),
           max_deviation=worst, tolerances=dict(vol_rel=verify.TOL_SRC_VOL, centroid_mm=verify.TOL_SRC_CEN, bbox_mm=verify.TOL_SRC_BBOX),
           failing=bad[:50], n_failing=len(bad), name_mismatch=name_bad[:50], n_name_mismatch=len(name_bad),
           labels_checked=sum(1 for r in rows if r['in_step'] and r['in_ifc']),
           per_instance_file=os.path.basename(outp) + '.csv.gz',
           reference='IfcOpenShell kernel geometry of the IFC (verify.source_props) vs OpenCASCADE B-rep of the shipped '
                     'STEP (occstep.delivered_props); ids = sds2label.guid(sha256 of shipped STEP, instance label)',
           seconds=dict(step=round(t1 - t0, 1), ifc=round(t2 - t1, 1), total=round(time.time() - t0, 1)))
res['reproduced'] = bool(res['matched'] and not res['n_only_in_step'] and not res['n_only_in_ifc']
                         and not res['n_failing'] and not res['n_name_mismatch'])
with open(outp + '.json', 'w') as fh:
    json.dump(res, fh, indent=1)
print(json.dumps({k: v for k, v in res.items() if k not in ('failing', 'only_in_step', 'only_in_ifc', 'name_mismatch')}))
