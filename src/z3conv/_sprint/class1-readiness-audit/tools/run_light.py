import json, os, subprocess, sys, concurrent.futures as cf
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KIT = sys.argv[1]; TAG = sys.argv[2]
PY = '/Users/dhiren/Downloads/Deccan/z3conv/db1_v2/_env/env/bin/python'
SRC = [os.path.join(ROOT, 'src'), '/Users/dhiren/Downloads/Deccan/z3conv/_fast/audit-db1-codes/src']
inv = json.load(open(os.path.join(ROOT, 'inventory.json')))
d = os.path.join(ROOT, 'runs', TAG); os.makedirs(d, exist_ok=True)
def one(sha):
    o = os.path.join(d, sha + '.json')
    if os.path.exists(o): return sha, 'cached'
    p = next((os.path.join(s, sha + '.db1') for s in SRC if os.path.exists(os.path.join(s, sha + '.db1'))), None)
    if not p: return sha, 'no_source'
    r = subprocess.run([PY, os.path.join(ROOT, 'tools/light_decode.py'), KIT, p, o], capture_output=True, text=True)
    return sha, r.returncode, r.stderr[-300:]
ids = sorted(inv, key=lambda k: inv[k]['size'] or 0)
with cf.ThreadPoolExecutor(int(os.environ.get('NPAR', '3'))) as ex:
    for res in ex.map(one, ids): print(*res, flush=True)
