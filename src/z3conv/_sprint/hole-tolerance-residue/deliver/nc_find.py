"""nc_find.py MODELS_JSON OUT_JSON : for every old-engine DB1, list DSTV NC files (*.nc1 / *.nc) under its folder, its parent and grandparent"""
import json, sys, os, collections, boto3, concurrent.futures as cf
s3 = boto3.client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'
M = [m for m in json.load(open(sys.argv[1])) if str(m['engine']) in ('6.87', '7.01', '7.24')]


def lst(prefix, cap=30000):
    out = []; tok = None
    while True:
        kw = dict(Bucket=B, Prefix=prefix, MaxKeys=1000)
        if tok: kw['ContinuationToken'] = tok
        r = s3.list_objects_v2(**kw)
        out += [(o['Key'], o['Size']) for o in r.get('Contents', [])]
        if not r.get('IsTruncated') or len(out) >= cap: return out
        tok = r['NextContinuationToken']


def find(m):
    k = m['input_key']; d1 = os.path.dirname(k); res = {}
    for lvl, d in (('model', d1), ('parent', os.path.dirname(d1)), ('grandparent', os.path.dirname(os.path.dirname(d1)))):
        if d.count('/') < 2: break
        L = lst(d + '/')
        nc = [(x, s) for x, s in L if x.lower().endswith(('.nc1', '.nc'))]
        db1s = [x for x, s in L if x.lower().endswith('.db1')]
        res[lvl] = {'prefix': d + '/', 'objects': len(L), 'nc': len(nc), 'db1s': len(db1s),
                    'nc_dirs': dict(collections.Counter(os.path.dirname(x) for x, s in nc).most_common(10)),
                    'ifc': [x for x, s in L if x.lower().endswith('.ifc')][:10]}
        if nc and len(db1s) <= 3: break
    return m['id'], res


with cf.ThreadPoolExecutor(16) as ex:
    R = dict(ex.map(find, M))
json.dump(R, open(sys.argv[2], 'w'), indent=1)
n = sum(1 for v in R.values() if any(x.get('nc') for x in v.values()))
print('models with nc files nearby:', n, 'of', len(R))
