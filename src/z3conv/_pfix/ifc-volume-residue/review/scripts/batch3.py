#!/usr/bin/env python3
"""reviewer batch: run_case3 over a models file for one config (label -> converter + kit); per model input download,
case run, upload of the small result files; STEP kept on the box for the reviewer's own checks.
usage: batch3.py LABEL CONV_DIR KIT_DIR MODELS.json --jobs N [--ids a,b]"""
import sys, os, json, subprocess, argparse, time, threading
from concurrent.futures import ThreadPoolExecutor
import boto3
ap = argparse.ArgumentParser(); ap.add_argument('label'); ap.add_argument('conv'); ap.add_argument('kit'); ap.add_argument('models')
ap.add_argument('--jobs', type=int, default=3); ap.add_argument('--ids', default=None); ap.add_argument('--threads', default='2')
a = ap.parse_args()
W = '/work/agentwork/ifc-volume-residue-review'
R_B, R_P = 'bim-proprietary-data', 'cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-volume-residue-review'
PY = '/opt/conv/env/bin/python'
s3 = boto3.client('s3', region_name='ap-south-1')
ms = json.load(open(a.models))
if a.ids:
    ms = [o for o in ms if o['id'][:16] in a.ids.split(',')]
ms.sort(key=lambda o: o['size'])
lock = threading.Lock()
os.makedirs(f'{W}/w/{a.label}', exist_ok=True); os.makedirs(f'{W}/in', exist_ok=True)
prog = f'{W}/w/{a.label}/progress.jsonl'


def up(path, name):
    try:
        s3.upload_file(path, R_B, f'{R_P}/{name}')
    except Exception as e:
        print('upload failed', path, e, flush=True)


def get_input(o):
    inp = f"{W}/in/{o['id'][:16]}.bin"
    with lock:
        pass
    if not (os.path.exists(inp) and os.path.getsize(inp) == o['size']):
        tmp = inp + '.%d.%d.part' % (os.getpid(), threading.get_ident())
        s3.download_file(R_B, o['input_key'], tmp); os.replace(tmp, inp)
    return inp


def one(o):
    i16 = o['id'][:16]
    wd = f'{W}/w/{a.label}/{i16}'
    cj = os.path.join(wd, 'case.json')
    if os.path.exists(cj):
        return o, json.load(open(cj))
    subprocess.run(['rm', '-rf', wd])
    inp = get_input(o)
    env = dict(os.environ, KIT=a.kit, COORD=f'{W}/pkg/coord', V6_VERIFY_PROCS=os.environ.get('V6_VERIFY_PROCS', '2'))
    t = time.time()
    r = subprocess.run([PY, f'{W}/pkg/run_case3.py', os.path.join(a.conv, 'ifc2step6.py'), inp, o['id'], wd, '--threads', a.threads],
                       capture_output=True, text=True, env=env)
    try:
        res = json.load(open(cj))
    except Exception:
        res = {'class': None, 'error': (r.stderr or '')[-1500:]}
        os.makedirs(wd, exist_ok=True); json.dump(res, open(cj, 'w'))
    for f in ('case.json', 'out.step.stats.json', 'out.step.parts.json', 'census.json', 'src_parts.jsonl.gz', 'step_parts.jsonl.gz', 'out.step.check.json'):
        p = os.path.join(wd, f)
        if os.path.exists(p):
            up(p, f'{a.label}/{i16}/{f}')
    lt = os.path.join(wd, 'log.txt')
    if os.path.exists(lt):
        with open(lt, errors='replace') as fh:
            tail = fh.read()[-20000:]
        open(lt + '.tail', 'w').write(tail); up(lt + '.tail', f'{a.label}/{i16}/log_tail.txt')
    line = {'id': o['id'], 'tag': o.get('tag'), 'size': o['size'], 'sec': round(time.time() - t, 1), 'class': res.get('class'),
            'reasons': res.get('reasons'), 'issues': res.get('issues'), 'cov': res.get('coverage_all'), 'error': res.get('error')}
    with lock:
        with open(prog, 'a') as fh:
            fh.write(json.dumps(line) + '\n')
        up(prog, f'{a.label}/progress.jsonl')
    return o, res


with ThreadPoolExecutor(a.jobs) as ex:
    for o, r in ex.map(one, ms):
        print(f"{o.get('tag')} {o['id'][:16]} {o['size']/1e6:8.2f}MB -> {r.get('class')} {r.get('reasons')} {r.get('issues')} {str(r.get('error',''))[-300:]}", flush=True)
print('BATCH DONE', a.label, flush=True)
