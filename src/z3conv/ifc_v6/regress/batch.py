#!/usr/bin/env python3
"""run_case over the test set for one converter. usage: batch.py LABEL CONVERTER.py [--jobs 4] [--filter tag] [--ids a,b] [--big]"""
import sys, os, json, subprocess, argparse, time
from concurrent.futures import ThreadPoolExecutor
ap = argparse.ArgumentParser(); ap.add_argument('label'); ap.add_argument('conv'); ap.add_argument('--jobs', type=int, default=4)
ap.add_argument('--filter', default=None); ap.add_argument('--ids', default=None); ap.add_argument('--big', action='store_true')
ap.add_argument('--testset', default='/tmp/v6/testset.json'); ap.add_argument('--indir', default='/tmp/v6/in'); ap.add_argument('--out', default='/tmp/v6/w')
ap.add_argument('--threads', default='2'); ap.add_argument('--redo', action='store_true')
a = ap.parse_args()
HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.environ.get('PYBIN', '/Users/dhiren/Downloads/Deccan/z3conv/ifc_v6/_env/env/bin/python')
ts = json.load(open(a.testset))
ts = [o for o in ts if (a.big or not o['big']) and (not a.filter or o['tag'].startswith(a.filter)) and (not a.ids or o['id'][:16] in a.ids.split(','))]
ts.sort(key=lambda o: -o['size'])
res = {}
def one(o):
    wd = os.path.join(a.out, a.label, o['id'][:16])
    cj = os.path.join(wd, 'case.json')
    if os.path.exists(cj) and not a.redo:
        return o, json.load(open(cj))
    if os.path.exists(wd): subprocess.run(['rm', '-rf', wd])
    inp = os.path.join(a.indir, o['id'][:16] + '.bin')
    r = subprocess.run([PY, os.path.join(HERE, 'run_case.py'), a.conv, inp, o['id'], wd, '--threads', a.threads], capture_output=True, text=True)
    try:
        return o, json.load(open(cj))
    except Exception:
        return o, {'class': None, 'error': (r.stderr or '')[-800:]}
with ThreadPoolExecutor(a.jobs) as ex:
    for o, r in ex.map(one, ts):
        print(f"{o['tag']:16s} {o['id'][:16]} {o['size']/1e6:8.2f}MB was {o['class']} {o['reasons']} -> {r.get('class')} {r.get('reasons')} {r.get('issues')} {r.get('sec')}s {r.get('error','')[-300:]}", flush=True)
