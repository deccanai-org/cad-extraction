"""Per IFC file: STEP (ifc2step5 hybrid) + OCC read-back (validate_step), GLB + OBJ (IfcConvert), PNG (render.py).
Resumable; manifest per file in WORK/convdone/<id>.json.

convert.py run [--workers 6] [--only ID ...] [--steps step,validate,glb,obj,png]
convert.py areas [--workers 4]     -> per-area composite PNGs (iso_ne, iso_sw, top, side)
"""
import os, sys, json, time, glob, argparse, subprocess, collections, traceback, shutil
import numpy as np
from common import *

DONE = os.path.join(WORK, 'convdone')
FAILF = os.path.join(WORK, 'fail', 'convert.jsonl')
PY = sys.executable
SRC = os.path.dirname(os.path.abspath(__file__))
IFCCONVERT = os.path.join(os.path.dirname(PY), 'IfcConvert')
RB_MAX = int(os.environ.get('RB_MAX_MB', '300')) << 20       # OCC read-back only below this STEP size
DEFL = os.environ.get('S3D_DEFLECTION', '0.005')          # m, linear tessellation deflection (STEP/GLB/OBJ)
ADEFL = os.environ.get('S3D_ANG_DEFLECTION', '0.6')      # rad


def sh(cmd, timeout, env=None):
    t = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    return r.returncode, r.stdout[-4000:], r.stderr[-2000:], round(time.time() - t, 1)


def outp(kind, man, ext):
    rel = man['ifc'].replace('ifc/', kind + '/', 1)[:-4] + ext
    p = os.path.join(OUT, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return rel, p


def convert_one(man, steps):
    ifc = os.path.join(OUT, man['ifc'])
    res = {'id': man['id'], 'ifc': man['ifc'], 'ifc_bytes': man['bytes'], 'elements': man['elements'], 'origin': man['origin'], 'kind': man['kind'],
           'area': man['area']}
    prev_p = os.path.join(DONE, man['id'] + '.json')
    prev = json.load(open(prev_p)) if os.path.exists(prev_p) else {}
    env = dict(os.environ, DEFLECTION=DEFL, ANG_DEFLECTION=ADEFL)
    # ---- STEP
    rel, stp = outp('step', man, '.step')
    if 'step' in steps and not (prev.get('step', {}).get('ok') and os.path.exists(stp)):
        rc, out, err, sec = sh([PY, os.path.join(SRC, 'ifc2step5.py'), ifc, stp + '.tmp', '--mode', 'hybrid', '--threads', '2'], 7200, env)
        st = {}
        try:
            st = json.loads(out.strip().splitlines()[-1])
        except Exception:
            pass
        ok = rc == 0 and os.path.exists(stp + '.tmp') and st.get('parts', 0) > 0
        if ok:
            os.replace(stp + '.tmp', stp)
            if os.path.exists(stp + '.tmp.stats.json'):
                os.replace(stp + '.tmp.stats.json', stp + '.stats.json')
        res['step'] = {'ok': ok, 'file': rel, 'bytes': os.path.getsize(stp) if ok else 0, 'sec': sec,
                       'parts': st.get('parts'), 'faces': st.get('faces'), 'transcode_products': st.get('transcode_products'),
                       'tess_products': st.get('tess_products'), 'rc': rc, 'err': None if ok else (err or out)[-500:]}
    elif 'step' in prev:
        res['step'] = prev['step']
    # ---- OCC read-back
    if 'validate' in steps and res.get('step', {}).get('ok'):
        vpath = stp + '.validate.json'
        if not (prev.get('validate', {}).get('read_status') == 'ok' and os.path.exists(vpath)):
            if res['step']['bytes'] < RB_MAX:
                rc, out, err, sec = sh([PY, os.path.join(SRC, 'validate_step.py'), stp], 3600, env)
                try:
                    v = json.loads(out.strip().splitlines()[-1])
                except Exception:
                    v = {'error': (err or out)[-300:]}
                v['sec'] = sec
                v['roots_match_parts'] = (v.get('transferred') == res['step'].get('parts')) if 'transferred' in v else None
            else:
                v = {'skipped': 'STEP >= %d MB' % (RB_MAX >> 20)}
            json.dump(v, open(vpath, 'w'))
            res['validate'] = v
        else:
            res['validate'] = prev['validate']
    # ---- GLB / OBJ via IfcConvert
    for kind, ext in (('glb', '.glb'), ('obj', '.obj')):
        sub = 'gltf' if kind == 'glb' else 'obj'
        rel, p = outp(sub, man, ext)
        if kind in steps and not (prev.get(kind, {}).get('ok') and os.path.exists(p)):
            tmp = p[:-len(ext)] + '.tmp' + ext
            cmd = [IFCCONVERT, '-y', '-j', '2', '--no-progress', '--use-element-guids', '--mesher-linear-deflection', DEFL,
                   '--mesher-angular-deflection', ADEFL, ifc, tmp]
            rc, out, err, sec = sh(cmd, 7200, env)
            ok = rc == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 0
            info = {'ok': ok, 'file': rel, 'sec': sec, 'rc': rc}
            if ok:
                os.replace(tmp, p)
                if kind == 'obj' and os.path.exists(tmp[:-4] + '.mtl'):
                    os.replace(tmp[:-4] + '.mtl', p[:-4] + '.mtl')
                    # point the obj at the renamed mtl
                    subprocess.run(['sed', '-i', 's/%s/%s/' % (os.path.basename(tmp[:-4]) + '.mtl', os.path.basename(p[:-4]) + '.mtl'), p])
                info['bytes'] = os.path.getsize(p)
                try:
                    import trimesh
                    m = trimesh.load(p, force='scene')
                    b = m.bounds
                    info['meshes'] = len(m.geometry); info['triangles'] = int(sum(len(g.faces) for g in m.geometry.values() if hasattr(g, 'faces')))
                    info['bounds'] = [round(float(x), 3) for x in b.reshape(-1)] if b is not None else None
                except Exception as e:
                    info['readback_error'] = str(e)[:200]
            else:
                info['err'] = (err or out)[-400:]
            res[kind] = info
        elif kind in prev:
            res[kind] = prev[kind]
    # ---- PNG (from GLB)
    if 'png' in steps and res.get('glb', {}).get('ok'):
        rel, p = outp('png', man, '')
        if not (prev.get('png') and all(os.path.exists(os.path.join(OUT, x)) for x in prev['png'].get('files', []))):
            import render
            try:
                out = render.render(render.load_scene([os.path.join(OUT, res['glb']['file'])]), p, ('iso_ne',), (1280, 960))
                res['png'] = {'files': [os.path.relpath(x['png'], OUT) for x in out], 'coverage': [x['coverage'] for x in out]}
            except Exception as e:
                res['png'] = {'files': [], 'error': '%s: %s' % (type(e).__name__, str(e)[:200])}
        else:
            res['png'] = prev['png']
    # ---- consistency: GLB bounds (Y-up) vs IFC manifest bbox
    return res


def _worker(a):
    man, steps = a
    t = time.time()
    try:
        res = convert_one(man, steps)
    except Exception as e:
        res = {'id': man['id'], 'error': '%s: %s' % (type(e).__name__, e), 'tb': traceback.format_exc()[-800:]}
    res['sec'] = round(time.time() - t, 1); res['at'] = utcnow()
    os.makedirs(DONE, exist_ok=True)
    write_json(os.path.join(DONE, man['id'] + '.json'), res, gz=False)
    bad = [k for k in ('step', 'glb', 'obj') if k in res and not res[k].get('ok')]
    if bad or 'error' in res:
        os.makedirs(os.path.dirname(FAILF), exist_ok=True)
        with open(FAILF, 'a') as f:
            f.write(json.dumps({'stage': 'convert', 'item': man['id'], 'reason': res.get('error') or ('failed: ' + ','.join(bad) + ' ' + str([res[k].get('err') for k in bad])[:300])}) + '\n')
    return {'id': man['id'], 'sec': res['sec'], 'step_mb': round(res.get('step', {}).get('bytes', 0) / 1e6, 1),
            'val': (res.get('validate') or {}).get('read_status') or (res.get('validate') or {}).get('skipped'), 'bad': bad, 'err': res.get('error')}


def summary():
    s = collections.Counter(); v = collections.Counter(); files = 0; mism = 0
    for f in glob.glob(os.path.join(DONE, '*.json')):
        r = json.load(open(f)); files += 1
        for k in ('step', 'glb', 'obj'):
            if k in r:
                s[k + ('_ok' if r[k].get('ok') else '_fail')] += 1
                s[k + '_mb'] += (r[k].get('bytes') or 0) / 1e6
        if r.get('png'):
            s['png'] += len(r['png'].get('files', []))
        val = r.get('validate') or {}
        if val.get('read_status') == 'ok':
            v['read_ok'] += 1; v['solids'] += val.get('solids', 0); v['faces'] += val.get('faces', 0)
            if val.get('roots_match_parts') is False:
                mism += 1
        elif val.get('skipped'):
            v['skipped_size'] += 1
        elif val:
            v['read_fail'] += 1
    out = {'files': files, 'outputs': {k: (round(x, 1) if isinstance(x, float) else x) for k, x in s.items()}, 'step_readback': dict(v),
           'step_roots_ne_parts': mism}
    json.dump(out, open(os.path.join(WORK, 'convert_summary.json'), 'w'), indent=1)
    return out


def run(workers, only=None, steps=('step', 'validate', 'glb', 'obj', 'png'), kind=None):
    mans = [json.load(open(f)) for f in sorted(glob.glob(os.path.join(WORK, 'ifcdone', '*.json')))]
    if only:
        mans = [m for m in mans if m['id'] in only]
    if kind:
        mans = [m for m in mans if m['kind'] == kind]
    def done(m):
        p = os.path.join(DONE, m['id'] + '.json')
        if not os.path.exists(p):
            return False
        r = json.load(open(p))
        return all(k in r and (k == 'validate' or k == 'png' or r[k].get('ok')) for k in steps if k != 'validate') and 'error' not in r
    todo = [m for m in mans if not done(m)]
    todo.sort(key=lambda m: -m['bytes'])
    log('convert: %d/%d files to process, %d workers, steps %s' % (len(todo), len(mans), workers, ','.join(steps)))
    import multiprocessing as mp
    t0 = time.time(); n = 0
    with mp.get_context('spawn').Pool(workers, maxtasksperchild=10) as pool:
        for r in pool.imap_unordered(_worker, [(m, steps) for m in todo]):
            n += 1
            log('%d/%d %.0fs %s' % (n, len(todo), time.time() - t0, json.dumps(r)[:300]))
            if n % 5 == 0:
                summary()
    log('convert done %s' % json.dumps(summary()))


def _area_worker(a):
    area, recs = a
    import render
    glbs = [os.path.join(OUT, r['glb']['file']) for r in recs]
    ref = np.array(recs[0]['origin'])
    offs = [list(np.array(r['origin']) - ref) for r in recs]
    prefix = os.path.join(OUT, 'png', safe_name(area.replace('/', '__'), 90), '_area')
    try:
        out = render.render(render.load_scene(glbs, offs), prefix, ('iso_ne', 'iso_sw', 'top', 'side'), (1600, 1200))
        meta = {'area': area, 'origin_ifc_frame': list(ref), 'sources': [r['id'] for r in recs], 'views': out}
        json.dump(meta, open(prefix + '.json', 'w'), indent=1, default=float)
        return {'area': area, 'pngs': len(out)}
    except Exception as e:
        return {'area': area, 'error': '%s: %s' % (type(e).__name__, str(e)[:200])}


def areas(workers):
    by = collections.defaultdict(list)
    for f in glob.glob(os.path.join(DONE, '*.json')):
        r = json.load(open(f))
        if r.get('glb', {}).get('ok'):
            by[r['area']].append(r)
    jobs = [(a, sorted(v, key=lambda r: r['id'])) for a, v in sorted(by.items())]
    log('area renders: %d areas' % len(jobs))
    import multiprocessing as mp
    with mp.get_context('spawn').Pool(workers, maxtasksperchild=4) as pool:
        for r in pool.imap_unordered(_area_worker, jobs):
            log(json.dumps(r))


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('cmd'); ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--only', nargs='*'); ap.add_argument('--steps', default='step,validate,glb,obj,png'); ap.add_argument('--kind')
    a = ap.parse_args()
    if a.cmd == 'run':
        run(a.workers, a.only, tuple(a.steps.split(',')), a.kind)
    elif a.cmd == 'areas':
        areas(a.workers)
    elif a.cmd == 'summary':
        print(json.dumps(summary(), indent=1))
