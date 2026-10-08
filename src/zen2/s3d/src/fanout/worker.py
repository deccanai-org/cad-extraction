#!/usr/bin/env python3
"""S3D 3D-data conversion worker (no database access needed).

Reads   s3://annotationprod/cad-disk-extract/zenitude-data-2/_control/s3d3d/jobs.json
Claims  s3://annotationprod/cad-disk-extract/zenitude-data-2/_state/s3d3d/claims/<id>.json   (PutObject IfNoneMatch='*')
Input   s3://annotationprod/<job.input_key>                                    (IFC4 file, model/ifc/<area>/<id>.ifc)
Writes  model/step/<area>/<id>.step (+.stats.json, .validate.json), model/gltf/<area>/<id>.glb,
        model/obj/<area>/<id>.obj (+.mtl), model/png/<area>/<id>__iso_ne.png
        result: _state/s3d3d/results/<id>.json ; heartbeat: _state/s3d3d/workers/<host>.json
Area composite renders (job kind 'area_png') run once all chunk jobs of that area have results.

usage:  python worker.py [--slots N] [--work /mnt/s3d3d] [--local-root DIR] [--once]
Everything written stays under s3://annotationprod/cad-disk-extract/zenitude-data-2/.
"""
import os, sys, json, time, socket, argparse, subprocess, traceback, shutil, random, threading, datetime
import concurrent.futures as cf

B = 'annotationprod'
ROOT = 'cad-disk-extract/zenitude-data-2'
CTL = ROOT + '/_control/s3d3d'
ST = ROOT + '/_state/s3d3d'
HOST = socket.gethostname()
HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
IFCCONVERT = os.path.join(os.path.dirname(PY), 'IfcConvert')
DEFL, ADEFL = '0.005', '0.6'          # tessellation: 5 mm linear / 0.6 rad angular (STEP, GLB, OBJ)
RB_MAX = int(os.environ.get('RB_MAX_MB', '300')) << 20
STALE_S = int(os.environ.get('CLAIM_STALE_S', str(4 * 3600)))

import boto3
from botocore.exceptions import ClientError
from botocore.config import Config
s3 = boto3.client('s3', config=Config(retries={'max_attempts': 10, 'mode': 'adaptive'}, max_pool_connections=64))


def now():
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


def exists(key):
    try:
        s3.head_object(Bucket=B, Key=key); return True
    except ClientError:
        return False


def put_json(key, obj):
    assert key.startswith(ROOT + '/')
    s3.put_object(Bucket=B, Key=key, Body=json.dumps(obj, default=str).encode(), ContentType='application/json')


def upload(path, key):
    assert key.startswith(ROOT + '/')
    s3.upload_file(path, B, key)


def claim(jid):
    key = '%s/claims/%s.json' % (ST, jid)
    body = json.dumps({'host': HOST, 'at': now(), 'pid': os.getpid()}).encode()
    try:
        s3.put_object(Bucket=B, Key=key, Body=body, IfNoneMatch='*'); return True
    except ClientError as e:
        if e.response.get('Error', {}).get('Code') not in ('PreconditionFailed', '412', 'ConditionalRequestConflict', '409'):
            raise
    try:
        age = time.time() - s3.head_object(Bucket=B, Key=key)['LastModified'].timestamp()
    except ClientError:
        return False
    if age > STALE_S and not exists('%s/results/%s.json' % (ST, jid)):
        s3.put_object(Bucket=B, Key=key, Body=body)       # stale claim: take over
        return True
    return False


def sh(cmd, timeout, env=None):
    t = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    return r.returncode, r.stdout[-4000:], r.stderr[-2000:], round(time.time() - t, 1)


def keys_for(job):
    ik = job['input_key']                       # .../model/ifc/<area>/<id>.ifc
    base = ik[:-4]
    return {k: base.replace('/model/ifc/', '/model/%s/' % d, 1) + ext for k, d, ext in
            (('step', 'step', '.step'), ('glb', 'gltf', '.glb'), ('obj', 'obj', '.obj'), ('mtl', 'obj', '.mtl'), ('png', 'png', ''))}


PNG = False


def run_chunk(job, work, local_root=None):
    t0 = time.time()
    K = keys_for(job)
    d = os.path.join(work, job['id']); os.makedirs(d, exist_ok=True)
    ifc = os.path.join(d, 'in.ifc')
    lp = os.path.join(local_root, job['input_key'].split('/model/', 1)[1]) if local_root else None
    if lp and os.path.exists(lp):
        shutil.copyfile(lp, ifc)
    else:
        s3.download_file(B, job['input_key'], ifc)
    env = dict(os.environ, DEFLECTION=DEFL, ANG_DEFLECTION=ADEFL)
    res = {'id': job['id'], 'area': job.get('area'), 'kind': job.get('kind'), 'input_key': job['input_key'], 'ifc_bytes': os.path.getsize(ifc),
           'host': HOST, 'origin': job.get('origin'), 'elements': job.get('elements')}
    # STEP (ifc2step5 hybrid: transcode faceted items, tessellate the rest)
    stp = os.path.join(d, 'out.step')
    rc, out, err, sec = sh([PY, os.path.join(HERE, 'ifc2step5.py'), ifc, stp, '--mode', 'hybrid', '--threads', '2'], 4 * 3600, env)
    st = {}
    try:
        st = json.loads(out.strip().splitlines()[-1])
    except Exception:
        pass
    ok = rc == 0 and os.path.exists(stp) and st.get('parts', 0) > 0
    res['step'] = {'ok': ok, 'key': K['step'], 'bytes': os.path.getsize(stp) if ok else 0, 'sec': sec, 'parts': st.get('parts'),
                   'faces': st.get('faces'), 'tess_products': st.get('tess_products'), 'transcode_products': st.get('transcode_products'),
                   'err': None if ok else (err or out)[-400:]}
    if ok:
        # OCC read-back (authoritative), below RB_MAX
        if res['step']['bytes'] < RB_MAX:
            rc, out, err, sec = sh([PY, os.path.join(HERE, 'validate_step.py'), stp], 3 * 3600, env)
            try:
                v = json.loads(out.strip().splitlines()[-1])
            except Exception:
                v = {'error': (err or out)[-300:]}
            v['sec'] = sec
            v['roots_match_parts'] = (v.get('transferred') == st.get('parts')) if 'transferred' in v else None
        else:
            v = {'skipped': 'STEP >= %d MB' % (RB_MAX >> 20)}
        v.pop('file', None)
        res['validate'] = v
        json.dump(v, open(stp + '.validate.json', 'w'))
        upload(stp, K['step'])
        if os.path.exists(stp + '.stats.json'):
            upload(stp + '.stats.json', K['step'] + '.stats.json')
        upload(stp + '.validate.json', K['step'] + '.validate.json')
    # GLB + OBJ (IfcConvert)
    for kind, ext in (('glb', '.glb'), ('obj', '.obj')):
        p = os.path.join(d, 'out' + ext)
        rc, out, err, sec = sh([IFCCONVERT, '-y', '-j', '2', '--no-progress', '--use-element-guids', '--mesher-linear-deflection', DEFL,
                                '--mesher-angular-deflection', ADEFL, ifc, p], 4 * 3600, env)
        okk = rc == 0 and os.path.exists(p) and os.path.getsize(p) > 0
        info = {'ok': okk, 'key': K[kind], 'sec': sec}
        if okk:
            if kind == 'obj' and os.path.exists(p[:-4] + '.mtl'):
                mt = os.path.basename(K['mtl'])
                subprocess.run(['sed', '-i', 's/^mtllib .*/mtllib %s/' % mt, p])
                upload(p[:-4] + '.mtl', K['mtl'])
            info['bytes'] = os.path.getsize(p)
            try:
                import trimesh
                m = trimesh.load(p, force='scene')
                info['meshes'] = len(m.geometry)
                info['triangles'] = int(sum(len(g.faces) for g in m.geometry.values() if hasattr(g, 'faces')))
                b = m.bounds
                info['bounds'] = [round(float(x), 3) for x in b.reshape(-1)] if b is not None else None
            except Exception as e:
                info['readback_error'] = str(e)[:200]
            upload(p, K[kind])
        else:
            info['err'] = (err or out)[-400:]
        res[kind] = info
    # PNG (iso view of the densest cluster) - separate process: the EGL context is not thread-safe
    if PNG and res['glb']['ok']:
        rc, out, err, sec = sh([PY, os.path.join(HERE, 'render.py'), os.path.join(d, 'r'), os.path.join(d, 'out.glb'),
                                '--views', 'iso_ne', '--size', '1280x960'], 1800, env)
        try:
            outp = json.loads(out.strip().splitlines()[-1]); files = []
            for x in outp:
                key = K['png'] + '__%s.png' % x['view']
                upload(x['png'], key); files.append(key)
            res['png'] = {'keys': files, 'coverage': [x['coverage'] for x in outp], 'sec': sec}
        except Exception as e:
            res['png'] = {'keys': [], 'error': '%s: %s %s' % (type(e).__name__, str(e)[:100], (err or out)[-300:])}
    res['sec'] = round(time.time() - t0, 1); res['at'] = now()
    shutil.rmtree(d, ignore_errors=True)
    return res


def run_area(job, work):
    import numpy as np
    d = os.path.join(work, job['id']); os.makedirs(d, exist_ok=True)
    glbs, origins = [], []
    budget = int(os.environ.get('AREA_GLB_BUDGET_MB', '160')) << 20
    deps = list(job['deps'])
    # triangle budget: prefer structure/equipment chunks, then piping chunks nearest the area centre
    metas = {}
    for dep in deps:
        try:
            metas[dep] = json.loads(s3.get_object(Bucket=B, Key='%s/results/%s.json' % (ST, dep))['Body'].read())
        except ClientError:
            pass
    import numpy as np
    orgs = np.array([m.get('origin') or [0, 0, 0] for m in metas.values()] or [[0, 0, 0]], float)
    med = np.median(orgs, axis=0)
    order = sorted(metas, key=lambda k: (0 if k.startswith(('str__', 'equ__')) else 1,
                                         float(np.linalg.norm(np.array(metas[k].get('origin') or [0, 0, 0]) - med))))
    used = 0; deps = []
    for k in order:
        b = (metas[k].get('glb') or {}).get('bytes') or 0
        if deps and used + b > budget:
            continue
        deps.append(k); used += b
    for dep in deps:
        r = metas.get(dep)
        if not r or not r.get('glb', {}).get('ok'):
            continue
        p = os.path.join(d, dep + '.glb'); s3.download_file(B, r['glb']['key'], p)
        glbs.append(p); origins.append(r.get('origin') or [0, 0, 0])
    res = {'id': job['id'], 'area': job['area'], 'kind': 'area_png', 'host': HOST, 'sources': len(glbs), 'deps_total': len(job['deps'])}
    if glbs:
        ref = np.array(origins[0], float)
        offs = [list(np.array(o, float) - ref) for o in origins]
        rc, out, err, sec = sh([PY, os.path.join(HERE, 'render.py'), os.path.join(d, 'area')] + glbs +
                               ['--offsets', json.dumps(offs), '--views', 'iso_ne,iso_sw,top,side', '--size', '1600x1200'], 3600, dict(os.environ))
        outp = json.loads(out.strip().splitlines()[-1])
        keys = []
        for x in outp:
            key = '%s/model/png/%s/_area__%s.png' % (ROOT, job['area_safe'], x['view'])
            upload(x['png'], key); keys.append(key)
        put_json('%s/model/png/%s/_area.json' % (ROOT, job['area_safe']),
                 {'area': job['area'], 'origin_ifc_frame': list(ref), 'sources': deps, 'views': outp})
        res['png'] = {'keys': keys, 'coverage': [x['coverage'] for x in outp], 'sec': sec}
    res['at'] = now()
    shutil.rmtree(d, ignore_errors=True)
    return res


def do(job, work, local_root):
    try:
        res = run_area(job, work) if job.get('kind') == 'area_png' else run_chunk(job, work, local_root)
    except Exception as e:
        res = {'id': job['id'], 'error': '%s: %s' % (type(e).__name__, e), 'tb': traceback.format_exc()[-1500:], 'host': HOST, 'at': now()}
    put_json('%s/results/%s.json' % (ST, job['id']), res)
    return res


def jobs_growing(a):
    """the job list is still being published while IFC generation runs (_control/s3d3d/publishing flag)"""
    return exists(CTL + '/publishing')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--slots', type=int, default=max(1, (os.cpu_count() or 4) // 3))
    ap.add_argument('--work', default='/mnt/s3d3d' if os.path.isdir('/mnt') else '/tmp/s3d3d')
    ap.add_argument('--local-root', default=None, help='local mirror of .../model/ (skip IFC download when present)')
    ap.add_argument('--once', action='store_true')
    ap.add_argument('--jobs-key', default=CTL + '/jobs.json')
    ap.add_argument('--png', action='store_true', help='also render PNG previews (chunk iso + area composites); off by default')
    a = ap.parse_args()
    global PNG
    PNG = a.png
    os.makedirs(a.work, exist_ok=True)
    done_n = 0; lock = threading.Lock(); t0 = time.time()

    def heartbeat(extra=None):
        try:
            put_json('%s/workers/%s.json' % (ST, HOST), dict({'host': HOST, 'at': now(), 'slots': a.slots, 'done': done_n,
                                                              'uptime_s': round(time.time() - t0)}, **(extra or {})))
        except Exception:
            pass

    while True:
        jobs = json.loads(s3.get_object(Bucket=B, Key=a.jobs_key)['Body'].read())
        results = set()
        for page in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=ST + '/results/'):
            for o in page.get('Contents', []):
                results.add(o['Key'].rsplit('/', 1)[-1][:-5])
        claims = set()
        for page in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=ST + '/claims/'):
            for o in page.get('Contents', []):
                if time.time() - o['LastModified'].timestamp() < STALE_S:
                    claims.add(o['Key'].rsplit('/', 1)[-1][:-5])
        chunk = [j for j in jobs if j.get('kind') != 'area_png' and j['id'] not in results and j['id'] not in claims]
        area = [j for j in jobs if PNG and j.get('kind') == 'area_png' and j['id'] not in results and j['id'] not in claims
                and all(dep in results for dep in j['deps'])]
        pending_chunks = [j for j in jobs if j.get('kind') != 'area_png' and j['id'] not in results]
        todo = chunk + area
        heartbeat({'todo_visible': len(todo), 'pending_chunks': len(pending_chunks)})
        if not todo:
            if not pending_chunks and not [j for j in jobs if PNG and j.get('kind') == 'area_png' and j['id'] not in results] and not jobs_growing(a):
                print('all jobs done'); heartbeat({'state': 'finished'}); return
            if a.once:
                return
            time.sleep(60); continue
        # keep order (largest first) but spread workers a little; keep every slot busy
        head = todo[:a.slots * 4]; random.shuffle(head); todo = head + todo[a.slots * 4:]
        it = iter(todo); t_round = time.time()

        def submit_next(ex):
            if time.time() - t_round > 300:          # refresh job/claim view every 5 min
                return None
            for j in it:
                if claim(j['id']):
                    return ex.submit(do, j, a.work, a.local_root)
            return None
        with cf.ThreadPoolExecutor(a.slots) as ex:
            active = set()
            for _ in range(a.slots):
                f = submit_next(ex)
                if f is not None:
                    active.add(f)
            while active:
                fin, active = cf.wait(active, return_when=cf.FIRST_COMPLETED)
                for f in fin:
                    r = f.result()
                    with lock:
                        done_n += 1
                    print(now(), json.dumps({k: r.get(k) for k in ('id', 'sec', 'error')}), flush=True)
                    nf = submit_next(ex)
                    if nf is not None:
                        active.add(nf)
                heartbeat({'active': len(active)})
        if a.once:
            return


if __name__ == '__main__':
    main()
