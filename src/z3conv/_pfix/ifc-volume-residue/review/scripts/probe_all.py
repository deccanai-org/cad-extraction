#!/usr/bin/env python3
"""probe_all.py POOL.json OUT.jsonl --jobs N : download each source, run probe.py (timeout), delete the source"""
import sys, os, json, subprocess, argparse, threading
from concurrent.futures import ThreadPoolExecutor
import boto3
ap = argparse.ArgumentParser(); ap.add_argument('pool'); ap.add_argument('out'); ap.add_argument('--jobs', type=int, default=6)
a = ap.parse_args()
W = '/work/agentwork/ifc-volume-residue-review'
s3 = boto3.client('s3', region_name='ap-south-1')
pool = json.load(open(a.pool))
done = set()
if os.path.exists(a.out):
    for l in open(a.out):
        try: done.add(json.loads(l)['id'])
        except Exception: pass
lock = threading.Lock()
os.makedirs(f'{W}/pin', exist_ok=True)


def one(o):
    if o['id'] in done:
        return
    p = f"{W}/pin/{o['id'][:16]}.bin"
    try:
        s3.download_file('bim-proprietary-data', o['input_key'], p)
        r = subprocess.run(['/opt/conv/env/bin/python', f'{W}/pkg/probe.py', p, o['id']], capture_output=True, text=True, timeout=900)
        line = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else json.dumps({'id': o['id'], 'error': (r.stderr or '')[-400:]})
    except subprocess.TimeoutExpired:
        line = json.dumps({'id': o['id'], 'error': 'timeout'})
    except Exception as e:
        line = json.dumps({'id': o['id'], 'error': str(e)[:300]})
    finally:
        try: os.remove(p)
        except OSError: pass
    with lock:
        with open(a.out, 'a') as fh:
            fh.write(line + '\n')


with ThreadPoolExecutor(a.jobs) as ex:
    list(ex.map(one, pool))
print('PROBE DONE')
