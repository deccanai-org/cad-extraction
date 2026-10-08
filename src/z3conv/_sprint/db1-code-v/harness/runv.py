"""runv.py SEL.json OUTDIR NPAR : download each model + its NC dirs, run vnc.py with the hooked kit (kit_h), keep JSON"""
import json, os, sys, subprocess, concurrent.futures as cf, boto3, posixpath
s3 = boto3.client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'
SEL = json.load(open(sys.argv[1])); OUT = sys.argv[2]; NPAR = int(sys.argv[3]); W = '/opt/db1v'
os.makedirs(OUT, exist_ok=True)
def keys(prefix):
    ks = []; tok = None
    while True:
        kw = dict(Bucket=B, Prefix=prefix, MaxKeys=1000)
        if tok: kw['ContinuationToken'] = tok
        r = s3.list_objects_v2(**kw); ks += [o['Key'] for o in r.get('Contents', [])]
        if not r.get('IsTruncated'): return ks
        tok = r['NextContinuationToken']
def one(o):
    sha = o['sha'][:12]; d = os.path.join(W, 'm', sha); os.makedirs(d, exist_ok=True); dirs = []
    outp = os.path.join(OUT, sha + '.json')
    if os.path.exists(outp): return sha, 'cached'
    try:
        if not os.path.exists(d + '/model.db1'): s3.download_file(B, o['key'], d + '/model.db1.part'); os.replace(d + '/model.db1.part', d + '/model.db1')
        for i, (nd, n) in enumerate(o['nc_dirs'][:8]):
            nd_l = os.path.join(d, 'nc%d' % i); os.makedirs(nd_l, exist_ok=True); dirs.append(nd_l)
            if os.path.exists(nd_l + '/.done'): continue
            for k in keys(nd + '/'):
                if posixpath.dirname(k) == nd and k.lower().endswith(('.nc1', '.nc')):
                    f = os.path.join(nd_l, os.path.basename(k))
                    if not os.path.exists(f): s3.download_file(B, k, f)
            open(nd_l + '/.done', 'w').close()
        rc = subprocess.run(['nice', '-n', '15', '/opt/conv/ifc84/bin/python', W + '/h/vnc.py', os.environ.get('VKIT', W + '/kit_h'), d + '/model.db1', ','.join(dirs), outp],
                            capture_output=True, text=True, timeout=5400)
        return sha, (rc.stdout + rc.stderr).strip()[-300:]
    except Exception as e:
        return sha, f'ERR {e!r}'[:300]
with cf.ThreadPoolExecutor(NPAR) as ex:
    for sha, msg in ex.map(one, SEL): print(sha, msg.splitlines()[-1] if msg else '', flush=True)
print('DONE', flush=True)
