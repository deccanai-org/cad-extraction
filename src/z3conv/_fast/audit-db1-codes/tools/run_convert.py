"""Local A/B run of the code-f db1 converter (kit_f = exact copy of the deployed code-f files) on every data-3 6.87/7.01 model:
   DB1_BOLTS=1 (bolt code) vs DB1_BOLTS=0 (pre-bolt behaviour of the same code). Writes runs/<mode>/<id>.{ifc,json,json.parts.json.gz}"""
import json, os, subprocess, sys, concurrent.futures as cf
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
KIT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'kit_f')
TAG = sys.argv[2] if len(sys.argv) > 2 else 'f'
ONLY = set(sys.argv[3].split(',')) if len(sys.argv) > 3 and sys.argv[3] else None
PY = os.path.join(ROOT, 'venv/bin/python')
rows = json.load(open(os.path.join(ROOT, 'sources.json')))
LAY = json.load(open(os.path.join(KIT, 'layouts.json')))


def one(args):
    i, eng, mode = args
    d = os.path.join(ROOT, 'runs', f'{TAG}_{mode}'); os.makedirs(d, exist_ok=True)
    ifc = os.path.join(d, i + '.ifc'); st = os.path.join(d, i + '.json')
    if os.path.exists(st):
        return i, mode, 'cached'
    lp = os.path.join(d, i + '.layout.json'); json.dump(LAY.get(eng, {}).get('layout'), open(lp, 'w'))
    env = dict(os.environ, DB1_BOLTS='1' if mode == 'bolts' else '0', PYTHONDONTWRITEBYTECODE='1')
    r = subprocess.run([PY, os.path.join(KIT, 'convert_one.py'), os.path.join(ROOT, 'src', i + '.db1'), ifc, os.path.join(KIT, 'tekla_profiles.json'),
                        lp, st], env=env, capture_output=True, text=True, timeout=3600)
    os.remove(lp)
    return i, mode, r.returncode


jobs = []
for i, size, key, frm, eng, stt in rows:
    if stt != 'ok' or (ONLY and i[:12] not in ONLY):
        continue
    for mode in ('bolts', 'nobolts'):
        jobs.append((i, eng, mode))
with cf.ThreadPoolExecutor(int(os.environ.get('NPAR', '4'))) as ex:
    for res in ex.map(one, jobs):
        print(*res, flush=True)
