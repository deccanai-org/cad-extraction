import sys, numpy as np, collections
import ifcopenshell.util.element as ue
exec(open('probe17.py').read().split("SENT = 2147483647")[0])
c = collections.Counter()
for e, m in pairs:
    ps = {}
    for k, v in ue.get_psets(e).items():
        if 'Bolt' in k or 'Fastener' in k: ps.update(v)
    nb = None
    c[(m['prof'], ps.get('Bolt hole diameter'), ps.get('Slotted hole x'), ps.get('Slotted hole y'), ps.get('Washer count'), ps.get('Nut count'), ps.get('Bolt count'), ps.get('Bolt standard'), ps.get('Location'))] += 1
for k, v in c.most_common(40): print(v, k)
