"""for failing data-4 DB1 jobs: Tekla IFC exports in the model folder / its parent (bim, read-only)"""
import boto3, json, sys, concurrent.futures as cf, os
s3 = boto3.Session(profile_name='bim').client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'
rows = json.load(open('../work/d4fail.json'))
sel = [r for r in rows if r[1] in ('no_member_layout', 'suspect_attr_link', 'unapproved_engine')]
def probe(r):
    key = r[4]; d = key.rsplit('/', 1)[0]; par = d.rsplit('/', 1)[0]
    out = []
    for pre, deep in ((d + '/', True), (par + '/', False)):
        kw = dict(Bucket=B, Prefix=pre) if deep else dict(Bucket=B, Prefix=pre, Delimiter='/')
        n = 0
        for pg in s3.get_paginator('list_objects_v2').paginate(**kw):
            for o in pg.get('Contents', []):
                n += 1
                if o['Key'].lower().endswith('.ifc') and 20_000 < o['Size'] < 400_000_000:
                    try:
                        h = s3.get_object(Bucket=B, Key=o['Key'], Range='bytes=0-2000')['Body'].read().decode('latin1')
                    except Exception: continue
                    if 'Tekla' in h: out.append((o['Key'], o['Size'], 'GridExporter' in h))
            if n > 20000: break
    return r, out
res = []
with cf.ThreadPoolExecutor(24) as ex:
    for r, out in ex.map(probe, sel):
        res.append(dict(engine=r[0], status=r[1], size=r[2], id=r[3], key=r[4], ifc=out))
        if out: print(r[0], r[1], r[3][:10], len(out), out[0][0][-90:], flush=True)
json.dump(res, open('d4fail_ifc.json', 'w'), indent=1)
print('with ifc', sum(1 for x in res if x['ifc']), 'of', len(res))
