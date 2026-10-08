#!/usr/bin/env python3
"""gr4.py PIPE JOB OUT.json : run grating.build() on every grating piece of a job (placed or not)."""
import sys, os, re, json, time, collections
import numpy as np
PIPE, job, outp = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, os.path.join(PIPE, 'decode'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from piece_table import read_pieces, slot_size, LAYOUTS
from instances import material_instances
from sds2job import read_members, read_version
import brep, grating
b = open(os.path.join(job, 'subm', 'subm_idx'), 'rb').read()
key = slot_size(b); Lo = LAYOUTS[key]; S = Lo['slot']
pieces = read_pieces(job)
gr = {k: p for k, p in pieces.items() if re.match(r'G[TR]\d', p['name'])}
mems, _ = read_members(job)
placed = collections.Counter()
for m in mems:
    try:
        _, inst = material_instances(job, m.id, pieces)
    except Exception:
        continue
    for sid, M, o in inst:
        if sid in gr: placed[sid] += 1
res = dict(job=job, version=read_version(job), layout=str(key), pieces=[])
summ = collections.Counter(); why = collections.Counter(); ratios = []
for k in sorted(gr, key=lambda k: -placed[k]):
    p = gr[k]
    d = dict(sid=k, name=p['name'], wt=round(p['wt'], 3), placed=placed[k])
    fp = os.path.join(job, 'subm', str(k))
    if not os.path.exists(fp):
        d['why'] = 'no piece file'; why[d['why']] += 1; res['pieces'].append(d); continue
    r = brep.parse(open(fp, 'rb').read())
    if r is None:
        d['why'] = 'no readable faces'; why[d['why']] += 1; res['pieces'].append(d); continue
    t0 = time.time()
    try:
        sh, info = grating.build(r[0], r[1], p['wt'], b[k * S:(k + 1) * S])
    except Exception as e:
        sh, info = None, dict(why=f'error {type(e).__name__}: {e}')
    d.update(info); d['sec'] = round(time.time() - t0, 2); d['ok'] = sh is not None
    summ['ok' if sh is not None else 'fail'] += 1
    summ['ok_placed' if sh is not None else 'fail_placed'] += placed[k]
    if sh is None: why[info.get('why', '?')] += 1
    if info.get('weight_ratio'): ratios.append(info['weight_ratio'])
    res['pieces'].append(d)
res['summary'] = dict(summ); res['why'] = dict(why)
if ratios:
    a = np.array(ratios); res['ratio_pct'] = [round(float(x), 4) for x in np.percentile(a, [0, 5, 25, 50, 75, 95, 100])]
json.dump(res, open(outp, 'w'), default=lambda o: o.item() if hasattr(o, 'item') else str(o))
print(job, res['version'], res['layout'], json.dumps(res['summary']), json.dumps(res['why'])[:300], res.get('ratio_pct'))
