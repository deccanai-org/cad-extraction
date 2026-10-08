"""Local decode-only run of a kit (DB1 -> decoder IFC + stats + per-bolt dump) on every data-3 DB1 model with a local source copy.
usage: run_audit.py KIT TAG [ids,comma] ; NPAR env (default 3). Writes runs/<TAG>/<sha>.{json,dump.json}; IFC deleted unless KEEP_IFC=1"""
import json, os, subprocess, sys, zlib, re, time, concurrent.futures as cf
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
KIT = os.path.abspath(sys.argv[1]); TAG = sys.argv[2]
ONLY = set(sys.argv[3].split(',')) if len(sys.argv) > 3 and sys.argv[3] else None
PY = '/Users/dhiren/Downloads/Deccan/z3conv/db1_v2/_env/env/bin/python'
SRC = [os.path.join(ROOT, 'src'), '/Users/dhiren/Downloads/Deccan/z3conv/_fast/audit-db1-codes/src']
LAY = json.load(open(os.path.join(KIT, 'layouts.json')))
inv = json.load(open(os.path.join(ROOT, 'inventory.json')))


def src_of(sha):
    for d in SRC:
        p = os.path.join(d, sha + '.db1')
        if os.path.exists(p) and os.path.getsize(p) > 0:
            return p
    return None


def engine_of(path):
    raw = open(path, 'rb').read(1 << 16)
    data = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw) if raw[:2] == b'\x1f\x8b' else raw
    m = re.search(rb'(\d+\.\d+)', data[:16])
    return m.group(1).decode() if m else None


def one(sha):
    d = os.path.join(ROOT, 'runs', TAG); os.makedirs(d, exist_ok=True)
    st = os.path.join(d, sha + '.json')
    if os.path.exists(st):
        return sha, 'cached', 0
    p = src_of(sha)
    if not p:
        return sha, 'no_source', 0
    eng = engine_of(p)
    if eng not in LAY or not LAY[eng].get('approved'):
        json.dump({'status': 'unapproved_engine', 'engine': eng}, open(st, 'w'))
        return sha, f'unapproved {eng}', 0
    lp = os.path.join(d, sha + '.layout.json'); json.dump(LAY[eng].get('layout'), open(lp, 'w'))
    vp = os.path.join(d, sha + '.variants.json'); json.dump([v['layout'] for v in LAY.values() if v.get('layout')], open(vp, 'w'))
    ifc = os.path.join(d, sha + '.ifc')
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', DB1_AUDIT_DUMP=os.path.join(d, sha + '.dump.json'))
    t = time.time()
    r = subprocess.run([PY, os.path.join(KIT, 'convert_one.py'), p, ifc, os.path.join(KIT, 'tekla_profiles.json'), lp, st, vp],
                       env=env, capture_output=True, text=True, timeout=7200)
    for f in (lp, vp):
        os.remove(f)
    if not os.environ.get('KEEP_IFC') and os.path.exists(ifc):
        os.remove(ifc)
    try:
        s = json.load(open(st)); s['engine_banner'] = eng; s['run_sec'] = round(time.time() - t, 1); json.dump(s, open(st, 'w'), default=str)
    except Exception:
        pass
    return sha, r.returncode, round(time.time() - t, 1)


ids = [k for k in inv if (not ONLY or k[:12] in ONLY)]
ids.sort(key=lambda k: inv[k]['size'] or 0)
with cf.ThreadPoolExecutor(int(os.environ.get('NPAR', '3'))) as ex:
    for res in ex.map(one, ids):
        print(*res, flush=True)
