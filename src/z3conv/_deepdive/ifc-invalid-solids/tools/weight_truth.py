#!/usr/bin/env python3
"""Ground truth for per-part volume on SDS/2 IFC exports: Material_Net_Weight (lb or kg per the IFC mass unit) / steel
density -> expected volume (mm3).  Compares before / after step_check parts (matched by name, or GlobalId when the
STEP carries it) and reports how many parts are within 5% of the weight-derived volume before and after.
usage: weight_truth.py SRC.ifc BEFORE.parts.jsonl.gz AFTER.parts.jsonl.gz [--show N]"""
import sys, json, gzip, collections, statistics, argparse
import ifcopenshell

ap = argparse.ArgumentParser(); ap.add_argument('ifc'); ap.add_argument('before'); ap.add_argument('after'); ap.add_argument('--show', type=int, default=8)
a = ap.parse_args()
f = ifcopenshell.open(a.ifc)
mass_unit = 'lb'
try:
    for u in f.by_type('IfcUnitAssignment')[0].Units:
        if getattr(u, 'UnitType', None) == 'MASSUNIT':
            mass_unit = 'kg' if u.is_a('IfcSIUnit') else (u.Name or 'lb').lower()
except Exception:
    pass
KG = 0.45359237 if 'pound' in mass_unit or mass_unit == 'lb' else 1.0
RHO = 7849.0  # kg/m3 (SDS/2 steel 0.2836 lb/in3)
truth_g, truth_n = {}, collections.defaultdict(list)
for p in f.by_type('IfcProduct'):
    w = None
    for d in getattr(p, 'IsDefinedBy', []) or []:
        if d.is_a('IfcRelDefinesByProperties'):
            ps = d.RelatingPropertyDefinition
            for q in getattr(ps, 'HasProperties', []) or []:
                if q.Name == 'Material_Net_Weight' and getattr(q, 'NominalValue', None) is not None:
                    w = float(q.NominalValue.wrappedValue)
    if w and w > 0:
        v = w * KG / RHO * 1e9
        truth_g[p.GlobalId] = v; truth_n[p.Name or ''].append(v)


def load(fn):
    return [json.loads(l) for l in gzip.open(fn, 'rt') if l.strip()]


B, A = load(a.before), load(a.after)
# pair parts by STEP PRODUCT.id (GlobalId in current writers) when unique, else by root order
cnt = collections.Counter(p.get('pid') for p in B)
byA = {p.get('pid'): p for p in A}
if all(n == 1 for n in cnt.values()) and len(byA) == len(A):
    pairs = [(x, byA.get(x.get('pid'))) for x in B]
    pairs = [(x, y) for x, y in pairs if y is not None]
else:
    pairs = list(zip(B, A))
stat = collections.Counter(); rows = []
for x, y in pairs:
    t = truth_g.get(x.get('pid'))
    if t is None:
        lst = truth_n.get(x.get('name') or '')
        if not lst or max(lst) > 1.02 * min(lst):
            continue
        t = statistics.median(lst)
    vb, va = x.get('volume'), y.get('volume')
    if vb is None or va is None:
        continue
    rb, ra = vb / t, va / t
    okb, oka = abs(rb - 1) <= 0.05, abs(ra - 1) <= 0.05
    stat['parts_with_weight'] += 1; stat['within5_before'] += okb; stat['within5_after'] += oka
    if abs(va - vb) > 1e-6 * max(abs(vb), 1):
        stat['volume_changed'] += 1; stat['changed_better'] += abs(ra - 1) < abs(rb - 1); stat['changed_worse'] += abs(ra - 1) > abs(rb - 1) + 1e-9
        rows.append((x.get('name'), round(t, 1), round(vb, 1), round(va, 1), round(rb, 3), round(ra, 3)))
print(json.dumps({'mass_unit': mass_unit, **stat}))
for r in sorted(rows, key=lambda r: -abs(r[4] - r[5]))[:a.show]:
    print('   name=%s truth=%s before=%s after=%s ratio %s -> %s' % r)
worse = [r for r in rows if abs(r[5] - 1) > abs(r[4] - 1) + 1e-9]
for r in sorted(worse, key=lambda r: -abs(r[5] - 1))[:a.show]:
    print('   WORSE name=%s truth=%s before=%s after=%s ratio %s -> %s' % r)
