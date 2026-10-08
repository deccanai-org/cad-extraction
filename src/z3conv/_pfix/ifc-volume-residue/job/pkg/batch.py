#!/usr/bin/env python3
"""run_case2 over models.json for one converter; per model: input download (boto3), run_case2, upload of the small
result files to S3 as they finish. usage: batch.py LABEL CONVERTER.py --models M.json --jobs 4 --out DIR --indir DIR --s3 s3://...
[--ids a,b] [--redo] [--max-mb N]"""
import sys, os, json, subprocess, argparse, time, threading
from concurrent.futures import ThreadPoolExecutor
import boto3
ap = argparse.ArgumentParser(); ap.add_argument('label'); ap.add_argument('conv'); ap.add_argument('--models', required=True)
ap.add_argument('--jobs', type=int, default=4); ap.add_argument('--out', required=True); ap.add_argument('--indir', required=True)
ap.add_argument('--s3', required=True); ap.add_argument('--ids', default=None); ap.add_argument('--redo', action='store_true')
ap.add_argument('--threads', default='2'); ap.add_argument('--max-mb', type=float, default=1e9)
a = ap.parse_args()
HERE = os.path.dirname(os.path.abspath(__file__))
PY = '/opt/conv/env/bin/python'
s3 = boto3.client('s3', region_name='ap-south-1')
bk, pre = a.s3[5:].split('/', 1)
ms = json.load(open(a.models))
ms = [o for o in ms if (not a.ids or o['id'][:16] in a.ids.split(',')) and o['size'] / 1e6 <= a.max_mb]
ms.sort(key=lambda o: o['size'])
lock = threading.Lock()
prog = os.path.join(a.out, a.label, 'progress.jsonl')
os.makedirs(os.path.dirname(prog), exist_ok=True)


def up(path, name):
    try:
        s3.upload_file(path, bk, f'{pre}/{name}')
    except Exception as e:
        print('upload failed', path, e, flush=True)


def one(o):
    i16 = o['id'][:16]
    wd = os.path.join(a.out, a.label, i16)
    cj = os.path.join(wd, 'case.json')
    if os.path.exists(cj) and not a.redo:
        return o, json.load(open(cj))
    if os.path.exists(wd):
        subprocess.run(['rm', '-rf', wd])
    inp = os.path.join(a.indir, i16 + '.bin')
    if not (os.path.exists(inp) and os.path.getsize(inp) == o['size']):
        s3.download_file('bim-proprietary-data', o['input_key'], inp + '.part'); os.replace(inp + '.part', inp)
    t = time.time()
    r = subprocess.run([PY, os.path.join(HERE, 'run_case2.py'), a.conv, inp, o['id'], wd, '--threads', a.threads], capture_output=True, text=True)
    try:
        res = json.load(open(cj))
    except Exception:
        res = {'class': None, 'error': (r.stderr or '')[-1500:]}
        os.makedirs(wd, exist_ok=True); json.dump(res, open(cj, 'w'))
    for f in ('case.json', 'out.step.stats.json', 'out.step.parts.json', 'census.json', 'src_parts.jsonl.gz', 'step_parts.jsonl.gz', 'out.step.check.json', 'out.step.png'):
        p = os.path.join(wd, f)
        if os.path.exists(p):
            up(p, f'{a.label}/{i16}/{f}')
    lt = os.path.join(wd, 'log.txt')
    if os.path.exists(lt):
        with open(lt, errors='replace') as fh:
            tail = fh.read()[-20000:]
        open(lt + '.tail', 'w').write(tail); up(lt + '.tail', f'{a.label}/{i16}/log_tail.txt')
    line = {'id': o['id'], 'group': o['group'], 'size': o['size'], 'sec': round(time.time() - t, 1), 'class_before': o['class_before'],
            'issues_before': o['issues_before'], 'class': res.get('class'), 'reasons': res.get('reasons'), 'issues': res.get('issues'),
            'standins': res.get('standins'), 'wr': res.get('weight_ratio'), 'error': res.get('error')}
    with lock:
        with open(prog, 'a') as fh:
            fh.write(json.dumps(line) + '\n')
        up(prog, f'{a.label}/progress.jsonl')
    return o, res


with ThreadPoolExecutor(a.jobs) as ex:
    for o, r in ex.map(one, ms):
        print(f"{o['group']} {o['id'][:16]} {o['size']/1e6:8.2f}MB was {o['class_before']} -> {r.get('class')} {r.get('reasons')} {r.get('issues')} {r.get('error','')[-300:]}", flush=True)
print('BATCH DONE', a.label, flush=True)
