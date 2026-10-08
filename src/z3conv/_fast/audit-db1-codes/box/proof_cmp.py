"""proof_cmp.py: STEP of the full patch set (proof/<id>_jfix2) vs the deployed STEP of the same model (newest of .j/.i/.h):
products, solids, invalid solids, parts without solid, approx share; polybeam parts: STEP volume vs profile area x full path length
(the deployed STEP holds area x first segment). out: report/proof_cmp.json"""
import json, os, re, sys, gzip, glob, math, collections
import numpy as np
W = os.path.dirname(os.path.abspath(__file__)); os.chdir(W)
sys.path.insert(0, os.path.join(W, 'kits', 'jfix2'))
import db1old, db1bolts, db1step
from db1dec import load
cat = json.load(open('kits/common/tekla_profiles.json'))
ov = json.load(open('kits/jfix2/tekla_profiles_overlay.json'))
out = {}


def sp(path):
    return [json.loads(l) for l in gzip.open(path, 'rt')] if os.path.exists(path) else []


def summ(chk, parts):
    C = json.load(open(chk)) if os.path.exists(chk) else {}
    return {'products': C.get('products'), 'solids': C.get('solids'), 'invalid': C.get('invalid'), 'nonpos': C.get('nonpos_vol'),
            'parts_without_solid': sum(1 for x in parts if not x.get('solids')), 'approx_products': C.get('approx_products'), 'bbox': C.get('bbox')}


for chk in sorted(glob.glob('proof/*_jfix2.check.json')):
    a = os.path.basename(chk).split('_')[0]
    i = [f[:-4] for f in os.listdir('src') if f.startswith(a)][0]
    P = sp(chk.replace('.check.json', '.parts.jsonl.gz'))
    dep = next((s for s in ('.j', '.i', '.h') if os.path.exists(f'out/{i}{s}.stp.check.json')), None)
    D = sp(f'det/{i}{dep}.step_parts.jsonl.gz') if dep else []
    r = {'patched': summ(chk, P), 'deployed_version': dep, 'deployed': summ(f'out/{i}{dep}.stp.check.json', D) if dep else None}
    # polybeam volumes
    h = __import__('hashlib').sha256(open(f'src/{i}.db1', 'rb').read()).hexdigest()
    c2 = dict(cat); c2.update({k: {'kind': v['kind'], 'dims': v['dims']} for k, v in (ov.get('global') or {}).items()})
    c2.update({k: {'kind': v['kind'], 'dims': v['dims']} for k, v in ((ov.get('per_model') or {}).get(h) or {}).items()})
    data = load(f'src/{i}.db1'); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
    M, info, _ = db1old.read(data, eng); by = {m['pid']: m for m in M}
    pl = json.load(gzip.open(f'dec/jfix2_audit2/{i}.json.parts.json.gz', 'rt'))
    vol = {x['pid']: x for x in P}
    rat = []; ex = []
    for pid, prof, cat_, stt, how, guid, nc in pl:
        m = by.get(pid)
        if stt != 'written' or not m or m.get('form') != 4 or len(m.get('old_poly') or []) < 3 or guid not in vol: continue
        if '[approx: polybeam' not in (vol[guid].get('name') or ''): continue
        kind, v, how_ = db1step.section_for(m['prof'], c2)
        o = db1bolts.outline(kind, v)
        if not o: continue
        poly = o[0]; area = abs(sum(poly[k][0] * poly[(k + 1) % len(poly)][1] - poly[(k + 1) % len(poly)][0] * poly[k][1] for k in range(len(poly)))) / 2
        area -= sum(abs(sum(q[k][0] * q[(k + 1) % len(q)][1] - q[(k + 1) % len(q)][0] * q[k][1] for k in range(len(q)))) / 2 for q in o[1])
        Q = np.array(m['old_poly'], float); path = float(np.linalg.norm(np.diff(Q, axis=0), axis=1).sum())
        exp = area * path; got = vol[guid].get('volume') or 0
        rat.append(got / exp if exp else 0)
        if len(ex) < 5: ex.append({'pid': pid, 'prof': m['prof'], 'L_first_segment': round(m['L'], 1), 'path': round(path, 1), 'segments': len(Q) - 1,
                                   'step_volume': round(got), 'area_x_path': round(exp), 'solids': vol[guid].get('solids'), 'valid': vol[guid].get('valid')})
    R = np.array(rat)
    r['polybeams'] = {'n': len(rat), 'volume_ratio_p5_p50_p95': [round(float(np.percentile(R, q)), 4) for q in (5, 50, 95)] if len(R) else None,
                      'within_3pct': int(np.sum(np.abs(R - 1) <= 0.03)), 'examples': ex}
    out[i] = r
    print(a, json.dumps({k: v for k, v in r.items() if k != 'polybeams'}), '\n   polybeams', json.dumps({k: v for k, v in r['polybeams'].items() if k != 'examples'}))
json.dump(out, open('report/proof_cmp.json', 'w'), indent=1)
