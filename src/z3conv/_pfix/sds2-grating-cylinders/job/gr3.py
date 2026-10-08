#!/usr/bin/env python3
"""gr3.py PIPE JOB OUT.json [N] : full V/F + slot bytes of the N most-placed grating pieces of each distinct face-size
signature (for designing the grating builder)."""
import sys, os, re, json, struct, collections
import numpy as np
PIPE, job, outp = sys.argv[1], sys.argv[2], sys.argv[3]
N = int(sys.argv[4]) if len(sys.argv) > 4 else 2
sys.path.insert(0, os.path.join(PIPE, 'decode'))
from piece_table import read_pieces, slot_size, LAYOUTS
from instances import material_instances
from sds2job import read_members, read_version
import brep
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
sigs = collections.defaultdict(list)
for k in sorted(gr, key=lambda k: -placed[k]):
    fp = os.path.join(job, 'subm', str(k))
    if not os.path.exists(fp): continue
    r = brep.parse(open(fp, 'rb').read())
    if r is None: continue
    sig = (gr[k]['name'][:2], tuple(sorted(collections.Counter(len(f) for f in r[1]).items())))
    if len(sigs[sig[0] + str(len(sigs))]) >= 0:
        pass
    sigs[sig].append((k, r))
out = dict(job=job, version=read_version(job), layout=str(key), pieces=[])
for sig, lst in sorted(sigs.items(), key=lambda kv: -sum(placed[k] for k, _ in kv[1]))[:6]:
    for k, (V, F) in lst[:N]:
        out['pieces'].append(dict(sid=k, name=gr[k]['name'], wt=gr[k]['wt'], placed=placed[k], sig=str(sig),
                                  slot=b[k * S:(k + 1) * S].hex(), V=np.round(V, 5).tolist(), F=[list(map(int, f)) for f in F]))
json.dump(out, open(outp, 'w'))
print(job, len(out['pieces']), [p['sig'][:60] for p in out['pieces']])
