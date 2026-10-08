"""runsec.py PAIRS.json OUTDIR NPAR"""
import json, os, sys, re, subprocess, concurrent.futures as cf, boto3
s3 = boto3.client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'
P = json.load(open(sys.argv[1])); OUT = sys.argv[2]; NPAR = int(sys.argv[3]); W = '/opt/db1v'; os.makedirs(OUT, exist_ok=True)
def one(r):
    h = r['sha'][:12] + '_' + re.sub(r'[^A-Za-z0-9]', '_', r['ifc'][-30:]); d = os.path.join(W, 'sm', h); os.makedirs(d, exist_ok=True)
    outp = os.path.join(OUT, h + '.json')
    if os.path.exists(outp): return h, 'cached'
    try:
        if not r.get('db1'):
            r['db1'] = json.loads(s3.get_object(Bucket=B, Key='cad-disk-extract/zentitude-data-4/_state/conv2/db1/results/' + r['sha'] + '.json')['Body'].read())['input_key']
        if not os.path.exists(d + '/m.db1'): s3.download_file(B, r['db1'], d + '/m.db1')
        if not os.path.exists(d + '/m.ifc'): s3.download_file(B, r['ifc'], d + '/m.ifc')
        rc = subprocess.run(['nice', '-n', '15', '/opt/conv/ifc84/bin/python', W + '/h/secck.py', W + '/kit_u', d + '/m.db1', d + '/m.ifc', outp],
                            capture_output=True, text=True, timeout=3600)
        if os.path.exists(outp):
            j = json.load(open(outp)); j['pair'] = r; json.dump(j, open(outp, 'w'))
        for f_ in ('m.db1', 'm.ifc'):
            try: os.remove(os.path.join(d, f_))
            except OSError: pass
        return h, (rc.stdout + rc.stderr).strip()[-400:]
    except Exception as e:
        return h, f'ERR {e!r}'[:300]
with cf.ThreadPoolExecutor(NPAR) as ex:
    for h, msg in ex.map(one, P): print(h, msg.replace('\n', ' | '), flush=True)
print('DONE', flush=True)
