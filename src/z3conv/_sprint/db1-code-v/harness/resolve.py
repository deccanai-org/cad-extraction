import json, os, posixpath, collections, concurrent.futures as cf, boto3
s3 = boto3.client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'
R4 = 'cad-disk-extract/zentitude-data-4/_state/conv2/db1/results/'
S = json.load(open('/opt/db1v/sel1.json'))
def lst(prefix, cap=20000):
    ks = []; tok = None
    while True:
        kw = dict(Bucket=B, Prefix=prefix, MaxKeys=1000)
        if tok: kw['ContinuationToken'] = tok
        r = s3.list_objects_v2(**kw); ks += [o['Key'] for o in r.get('Contents', [])]
        if not r.get('IsTruncated') or len(ks) > cap: return ks
        tok = r['NextContinuationToken']
def one(p):
    try:
        res = json.loads(s3.get_object(Bucket=B, Key=R4 + p['sha'] + '.json')['Body'].read())
        ik = res.get('input_key'); p['key'] = ik
        dirs = collections.Counter()
        for c in p['cands']:
            for k in c.get('nc_keys_sample') or []:
                if k and k.startswith('cad-disk-extract/'):
                    # direct: the whole nc dir of this candidate is stored under the same archive prefix
                    for d, n in c['nc_dirs']:
                        pref = k[:len(k) - len(posixpath.basename(c['path'])) ] if False else None
        # generic: list the model dir of the stored db1 copy and of each data-4 candidate archive
        roots = {posixpath.dirname(ik)} if ik else set()
        for c in p['cands']:
            if c.get('key', '') and str(c['key']).startswith('cad-disk-extract/'): roots.add(posixpath.dirname(c['key']))
            for k in c.get('nc_keys_sample') or []:
                if k and k.startswith('cad-disk-extract/'):
                    # model dir = key minus the nc's relative tail beyond the db1 dir
                    rel = posixpath.dirname(c['path'])
                    i = k.find('/' + rel + '/') if rel else -1
                    if i >= 0: roots.add(k[:i + 1 + len(rel)])
        for r in roots:
            for k in lst(r + '/'):
                if k.lower().endswith(('.nc1', '.nc')): dirs[posixpath.dirname(k)] += 1
        p['nc_dirs'] = dirs.most_common(); p['roots'] = sorted(roots)
    except Exception as e:
        p['err'] = repr(e)[:200]
    p.pop('cands', None)
    return p
with cf.ThreadPoolExecutor(16) as ex: out = list(ex.map(one, S))
json.dump(out, open('/opt/db1v/sel1r.json', 'w'))
c = collections.Counter((p['engine'], bool(p.get('nc_dirs'))) for p in out); print(sorted(c.items()))
