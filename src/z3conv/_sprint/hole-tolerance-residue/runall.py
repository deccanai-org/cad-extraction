"""runall.py KITDIR OUTDIR [all|hn] [workers] : harness over the bolt-engine models (smallest first)"""
import json, os, sys, subprocess, concurrent.futures as cf
KIT, OUTD = sys.argv[1], sys.argv[2]
which = sys.argv[3] if len(sys.argv) > 3 else 'hn'
W = int(sys.argv[4]) if len(sys.argv) > 4 else 3
PY = '/Users/dhiren/Downloads/Deccan/z3conv/db1_v2/_env/env/bin/python'
M = [m for m in json.load(open('models.json')) if str(m['engine']) in ('6.87', '7.01', '7.24')]
if which == 'hn':
    M = [m for m in M if m['hn']]
os.makedirs(OUTD, exist_ok=True)
M.sort(key=lambda m: m['size'])
def run(m):
    o = f"{OUTD}/{m['id'][:12]}.json"
    if os.path.exists(o):
        return m['id'][:12], 'cached'
    r = subprocess.run([PY, 'harness.py', KIT, f"db1/{m['id']}.db1", o], capture_output=True, text=True, timeout=3600)
    return m['id'][:12], r.returncode, (r.stdout or '')[-300:].strip(), (r.stderr or '')[-400:].strip() if r.returncode else ''
small = [m for m in M if m['size'] < 6e6]; big = [m for m in M if m['size'] >= 6e6]
with cf.ThreadPoolExecutor(W) as ex:
    for x in ex.map(run, small):
        print(*x, flush=True)
with cf.ThreadPoolExecutor(1) as ex:
    for x in ex.map(run, big):
        print(*x, flush=True)
