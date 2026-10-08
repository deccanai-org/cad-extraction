"""decode_all.py KITS NPAR [ONLY_IDS]: run every code's decoder (convert_one.py of that kit, ifcopenshell 0.8.4.post1 python as the
worker does) on every data-3 DB1 model with an approved engine -> dec/<kit>/<id>.{json,json.parts.json.gz,ifc[,audit.json]}"""
import json, os, sys, subprocess, time, zlib, re, concurrent.futures as cf
W = os.path.dirname(os.path.abspath(__file__)); os.chdir(W)
PY84 = '/opt/conv/ifc84/bin/python'
kits = sys.argv[1].split(','); npar = int(sys.argv[2]); only = set(sys.argv[3].split(',')) if len(sys.argv) > 3 and sys.argv[3] else None
jobs = json.load(open('state/all_jobs.json'))
LAY = json.load(open('kits/common/layouts.json'))
APPROVED = {e for e, v in LAY.items() if v.get('approved')}


def engine_of(path):
    raw = open(path, 'rb').read(1 << 16)
    data = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw) if raw[:2] == b'\x1f\x8b' else raw
    m = re.search(rb'(\d+\.\d+)', data[:16])
    return m.group(1).decode() if m else None


ENG = {}
for j in jobs:
    p = f"src/{j['id']}.db1"
    ENG[j['id']] = engine_of(p) if os.path.exists(p) else None
json.dump(ENG, open('state/engines.json', 'w'))
vp = 'state/variants.json'; json.dump([v['layout'] for v in LAY.values() if v.get('layout')], open(vp, 'w'))


def one(a):
    kit, j = a
    i = j['id']; eng = ENG.get(i)
    d = f'dec/{kit}' + (('_' + os.environ['DEC_TAG']) if os.environ.get('DEC_TAG') else ''); os.makedirs(d, exist_ok=True)
    st = f'{d}/{i}.json'
    if os.path.exists(st):
        return kit, i, 'cached', 0
    if eng not in APPROVED:
        json.dump({'status': 'unapproved_engine', 'engine': eng}, open(st, 'w')); return kit, i, 'unapproved', 0
    lp = f'{d}/{i}.layout.json'; json.dump(LAY[eng].get('layout'), open(lp, 'w'))
    env = dict(os.environ, DB1_BOLTS=os.environ.get('DB1_BOLTS', '1'), PYTHONDONTWRITEBYTECODE='1', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
    if '_audit' in kit:
        env['DB1_AUDIT'] = f'{d}/{i}.audit.json'
    t = time.time()
    try:
        r = subprocess.run([PY84, f'kits/{kit}/convert_one.py', f'src/{i}.db1', f'{d}/{i}.ifc', 'kits/common/tekla_profiles.json', lp, st + '.tmp', vp],
                           env=env, capture_output=True, text=True, timeout=5400)
        rc = r.returncode; err = r.stderr[-1500:]
    except subprocess.TimeoutExpired:
        rc = 124; err = 'timeout'
    os.remove(lp)
    if os.path.exists(st + '.tmp'):
        x = json.load(open(st + '.tmp')); x['_rc'] = rc; x['_sec'] = round(time.time() - t, 1); x['_engine'] = eng
        if os.path.exists(st + '.tmp.parts.json.gz'): os.replace(st + '.tmp.parts.json.gz', st + '.parts.json.gz')
        json.dump(x, open(st, 'w'), default=str); os.remove(st + '.tmp')
    else:
        json.dump({'status': 'no_stats', '_rc': rc, '_err': err, '_engine': eng}, open(st, 'w'))
    return kit, i, rc, round(time.time() - t, 1)


MAXMB = float(os.environ.get('DEC_MAX_MB', '1e9'))
todo = [(k, j) for k in kits for j in sorted(jobs, key=lambda j: -j['size']) if (not only or j['id'][:12] in only) and j['size'] <= MAXMB * 1e6]
t0 = time.time(); n = 0
with cf.ThreadPoolExecutor(npar) as ex:
    futs = [ex.submit(one, a) for a in todo]
    for fu in cf.as_completed(futs):
        n += 1
        try:
            res = fu.result()
        except Exception as e:
            res = ('?', '?', f'error {type(e).__name__}: {e}', 0)
        print(n, len(todo), *res, round(time.time() - t0), flush=True)
