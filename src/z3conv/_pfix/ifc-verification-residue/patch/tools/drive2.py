#!/usr/bin/env python3
"""Run a target list through rc.py (worker + classifier) with one converter, N slots, upload per-model results.
usage: drive.py LABEL CONVERTER.py TARGETS.json [--slots 4] [--threads 2] [--vprocs 2] [--ids a,b] [--keep-step-mb 300]"""
import sys, os, json, time, subprocess, argparse, gzip, shutil, threading
from concurrent.futures import ThreadPoolExecutor
import boto3
ap = argparse.ArgumentParser()
ap.add_argument('label'); ap.add_argument('conv'); ap.add_argument('targets')
ap.add_argument('--slots', type=int, default=4); ap.add_argument('--threads', default='2'); ap.add_argument('--vprocs', default='2')
ap.add_argument('--ids', default=None); ap.add_argument('--keep-step-mb', type=int, default=300); ap.add_argument('--redo', action='store_true')
a = ap.parse_args()
W = '/work/agentwork/ifc-verification-residue'
PY = '/opt/conv/env/bin/python'
B = 'bim-proprietary-data'
R = 'cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-verification-residue/' + a.label
s3 = boto3.client('s3', region_name='ap-south-1')
ts = json.load(open(a.targets))
if a.ids:
    want = a.ids.split(',')
    ts = [o for o in ts if any(o['id'].startswith(w) for w in want)]
lock = threading.Lock()
prog = {'label': a.label, 'conv': os.path.basename(a.conv), 'started': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'n': len(ts), 'done': {}, 'running': {}}


def put_prog():
    with lock:
        s3.put_object(Bucket=B, Key=R + '/progress.json', Body=json.dumps(prog, indent=1).encode())


def up(path, key):
    try:
        s3.upload_file(path, B, key)
    except Exception as e:
        print('upload fail', path, e, flush=True)


def one(o):
    i16 = o['id'][:16]
    wd = os.path.join(W, 'w', a.label, i16)
    cj = os.path.join(wd, 'case.json')
    if os.path.exists(cj) and not a.redo:
        r = json.load(open(cj))
    else:
        if os.path.exists(wd):
            shutil.rmtree(wd, ignore_errors=True)
        os.makedirs(wd, exist_ok=True)
        inp = os.path.join(W, 'in', i16 + '.bin')
        if not (os.path.exists(inp) and os.path.getsize(inp) == o['size']):
            s3.download_file(B, o['input_key'], inp + '.part'); os.rename(inp + '.part', inp)
        with lock:
            prog['running'][i16] = time.strftime('%H:%M:%SZ', time.gmtime())
        put_prog()
        env = dict(os.environ, V6_VERIFY_PROCS=a.vprocs, PYTHONDONTWRITEBYTECODE='1')
        t0 = time.time()
        p = subprocess.run([PY, os.path.join(W, 'job', 'rc2.py'), a.conv, inp, o['id'], wd, '--threads', a.threads,
                            '--kit', os.environ.get('KIT_DIR', os.path.join(W, 'kit')), '--coord', os.environ.get("COORD_DIR", os.path.join(W, "coord"))], capture_output=True, text=True, env=env)
        open(os.path.join(wd, 'rc.out'), 'w').write((p.stdout or '')[-20000:] + '\n---\n' + (p.stderr or '')[-20000:])
        try:
            r = json.load(open(cj))
        except Exception:
            r = {'class': None, 'error': (p.stderr or '')[-1500:], 'sec': round(time.time() - t0, 1)}
            json.dump(r, open(cj, 'w'))
    # uploads (small files only)
    for fn in ('case.json', 'rc.out', 'out.step.stats.json', 'out.step.check.json', 'census.json', 'src_parts.jsonl.gz', 'step_parts.jsonl.gz', 'out.step.png'):
        p_ = os.path.join(wd, fn)
        if os.path.exists(p_):
            up(p_, f'{R}/{i16}/{fn}')
    sc = os.path.join(wd, 'out.step.parts.json')
    if os.path.exists(sc):
        with open(sc, 'rb') as f, gzip.open(sc + '.gz', 'wb') as g:
            shutil.copyfileobj(f, g)
        up(sc + '.gz', f'{R}/{i16}/out.step.parts.json.gz')
    lg = os.path.join(wd, 'log.txt')
    if os.path.exists(lg):
        with open(lg, 'rb') as f:
            f.seek(max(0, os.path.getsize(lg) - 300000)); tail = f.read()
        open(lg + '.tail', 'wb').write(tail); up(lg + '.tail', f'{R}/{i16}/log.tail.txt')
    stp = os.path.join(wd, 'out.step')
    if os.path.exists(stp) and os.path.getsize(stp) > (a.keep_step_mb << 20):
        os.remove(stp)
    for x in ('in.bin', 'unz.ifc', 'hdr.ifc', 'merged.ifc', 'excl.ifc'):
        if os.path.exists(os.path.join(wd, x)):
            os.remove(os.path.join(wd, x))
    with lock:
        prog['running'].pop(i16, None)
        prog['done'][i16] = {k: r.get(k) for k in ('class', 'reasons', 'issues', 'standins', 'coverage_members', 'coverage_all', 'graded_by', 'status', 'fail_reason', 'sec', 'peak_tree_rss_mb', 'error')}
        st = r.get('stats') or {}
        prog['done'][i16].update(out_mb=round((st.get('out_bytes') or 0) / 1048576, 1), levels=st.get('levels'), tags=st.get('tags'),
                                 instancing=st.get('instancing'), was=o.get('was_issues'), was_class=o.get('was_class'), tag=o.get('tag'))
    put_prog()
    print(i16, json.dumps(prog['done'][i16], default=str)[:600], flush=True)
    return r


put_prog()
with ThreadPoolExecutor(a.slots) as ex:
    list(ex.map(one, ts))
prog['finished'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
put_prog()
print('ALL DONE', a.label, flush=True)
