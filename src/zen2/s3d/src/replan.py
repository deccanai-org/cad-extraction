"""Re-plan IFC jobs (split oversized pipelines), rebuild only new jobs, clean superseded outputs (local + S3).

replan.py plan      -> WORK/superseded.json, deletes superseded local IFC + manifests
replan.py clean     -> deletes S3 outputs/results/claims of superseded ids (safe to run repeatedly)
"""
import os, sys, json, glob
import boto3
from common import *
import ifcjobs

SUP = os.path.join(WORK, 'superseded.json')


def plan():
    old = {j['id']: j for j in json.load(open(ifcjobs.JOBF))}
    ifcjobs.plan()
    new = {j['id']: j for j in json.load(open(ifcjobs.JOBF))}
    sup = sorted(set(old) - set(new))
    add = sorted(set(new) - set(old))
    prev = json.load(open(SUP)) if os.path.exists(SUP) else []
    recs = []
    for i in sup:
        mp = os.path.join(ifcjobs.DONE, i + '.json')
        rel = None
        if os.path.exists(mp):
            rel = json.load(open(mp))['ifc']
            os.remove(mp)
        else:
            j = old[i]; rel = 'ifc/%s/%s.ifc' % (ifcjobs.area_safe(j.get('area')), i)
        if rel and os.path.exists(os.path.join(OUT, rel)):
            os.remove(os.path.join(OUT, rel))
        recs.append({'id': i, 'ifc': rel})
    json.dump(prev + recs, open(SUP, 'w'), indent=1)
    print('superseded', len(sup), 'new', len(add), add[:5])


def clean():
    s3 = boto3.client('s3')
    sup = json.load(open(SUP))
    n = 0
    for r in sup:
        base = r['ifc'][4:-4]                    # <area>/<id>
        keys = ['%s/ifc/%s.ifc' % (S3_PREFIX, base), '%s/step/%s.step' % (S3_PREFIX, base), '%s/step/%s.step.stats.json' % (S3_PREFIX, base),
                '%s/step/%s.step.validate.json' % (S3_PREFIX, base), '%s/gltf/%s.glb' % (S3_PREFIX, base), '%s/obj/%s.obj' % (S3_PREFIX, base),
                '%s/obj/%s.mtl' % (S3_PREFIX, base), '%s/png/%s__iso_ne.png' % (S3_PREFIX, base),
                'cad-disk-extract/zenitude-data-2/_state/s3d3d/results/%s.json' % r['id'],
                'cad-disk-extract/zenitude-data-2/_state/s3d3d/claims/%s.json' % r['id']]
        for k in keys:
            assert k.startswith('cad-disk-extract/zenitude-data-2/')
            try:
                s3.head_object(Bucket=S3_BUCKET, Key=k)
            except Exception:
                continue
            s3.delete_object(Bucket=S3_BUCKET, Key=k); n += 1
    print('deleted', n, 'objects for', len(sup), 'superseded ids')


if __name__ == '__main__':
    {'plan': plan, 'clean': clean}[sys.argv[1]]()
