"""runjob.py MODELS_JSON KITS(comma) OUTROOT WORKERS : fetch the old-engine DB1s (6.87/7.01/7.24) and run harness2 per kit; upload results"""
import json, os, sys, subprocess, concurrent.futures as cf, time
models = json.load(open(sys.argv[1])); kits = sys.argv[2].split(','); outroot = sys.argv[3]; W = int(sys.argv[4])
S3OUT = 's3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/hole-tolerance-residue'
PY = '/opt/conv/env/bin/python'
M = [m for m in models if str(m['engine']) in ('6.87', '7.01', '7.24')]
os.makedirs('db1', exist_ok=True)


def dl(m):
    p = f"db1/{m['id']}.db1"
    if not (os.path.exists(p) and os.path.getsize(p) == m['size']):
        subprocess.run(['aws', 's3', 'cp', '--quiet', f"s3://bim-proprietary-data/{m['input_key']}", p], check=False)
    return m['id'][:12], os.path.exists(p) and os.path.getsize(p) == m['size']


with cf.ThreadPoolExecutor(16) as ex:
    bad = [x for x in ex.map(dl, M) if not x[1]]
print('download failures', bad, flush=True)
jobs = [(k, m) for m in sorted(M, key=lambda m: -m['size']) for k in kits]


def run(km):
    k, m = km
    od = f"{outroot}/{k}"; os.makedirs(od, exist_ok=True)
    o = f"{od}/{m['id'][:12]}.json"
    if os.path.exists(o):
        return k, m['id'][:12], 'cached'
    t = time.time()
    try:
        r = subprocess.run([PY, 'harness2.py', k, f"db1/{m['id']}.db1", o], capture_output=True, text=True, timeout=7200)
        rc = r.returncode; err = r.stderr
    except subprocess.TimeoutExpired:
        rc = 'timeout'; err = 'timeout'
    if rc != 0:
        open(o + '.err', 'w').write(str(err)[-5000:])
    subprocess.run(['aws', 's3', 'cp', '--quiet', o if rc == 0 else o + '.err', f"{S3OUT}/{outroot}/{k}/"], check=False)
    return k, m['id'][:12], rc, round(time.time() - t, 1)


with cf.ThreadPoolExecutor(W) as ex:
    for x in ex.map(run, jobs):
        print(*x, flush=True)
print('ALLDONE', flush=True)
