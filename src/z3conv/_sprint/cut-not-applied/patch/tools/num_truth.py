"""num_truth.py NAME : bare-number-profile parts vs Tekla's own IFC export: Tekla NetVolume / Length / Width / Height vs (own outline area x number)"""
import sys, re, collections, numpy as np
W = '/work/agentwork/cut-not-applied'; NAME = sys.argv[1]
sys.path.insert(0, W + '/kitp4')
import db1old
from db1dec import load
import ifcopenshell, ifcopenshell.guid
data = load(f'{W}/truth/{NAME}.db1'); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
M, info, cr = db1old.read(data, eng); byp = {m['pid']: m for m in M}
f = ifcopenshell.open(f'{W}/truth/{NAME}.ifc'); tek = {}
for e in f.by_type('IfcElement'):
    q = {}
    for r in e.IsDefinedBy or []:
        if r.is_a('IfcRelDefinesByProperties') and r.RelatingPropertyDefinition.is_a('IfcPropertySet') and r.RelatingPropertyDefinition.Name == 'BaseQuantities':
            for x in r.RelatingPropertyDefinition.HasProperties:
                v = getattr(x, 'NominalValue', None)
                if v is not None and isinstance(v.wrappedValue, (int, float)): q[x.Name] = float(v.wrappedValue)
    tek[ifcopenshell.guid.expand(e.GlobalId).upper().replace('-', '')] = (e.is_a(), e.Name, getattr(e, 'ObjectType', None), q, getattr(e, 'Tag', None))
RX = re.compile(rb'([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})')
p2g = {}
for x in RX.finditer(data):
    s = x.group(1).decode().upper().replace('-', '')
    if s in tek:
        v = int.from_bytes(data[x.start() - 30:x.start() - 26], 'little', signed=True)
        if v in byp: p2g.setdefault(v, s)
n = 0
for m in M:
    if not m['prof'] or not re.fullmatch(r'\d+(\.\d+)?', m['prof']) or m['cut']: continue
    t = tek.get(p2g.get(m['pid']))
    P = m.get('old_poly') or []
    xy = np.array([(p[0], p[1]) for p in P]) if P else None
    area = abs(0.5 * sum(xy[i, 0] * xy[(i + 1) % len(xy), 1] - xy[(i + 1) % len(xy), 0] * xy[i, 1] for i in range(len(xy)))) if xy is not None and len(xy) >= 3 else None
    if n < 12:
        print(m['pid'], repr(m['prof']), 'L', round(m['L'], 1), 'form', m['form'], 'npts', len(P), 'outline area', round(area) if area else None,
              '| tekla', (t[0], t[1], t[2], {k: round(v, 4) for k, v in t[3].items() if k in ('NetVolume', 'Length', 'Width', 'Height')}) if t else None,
              '| area x number (m3)', round(area * float(m['prof']) / 1e9, 4) if area else None)
    n += 1
print('bare-number non-cut parts', n)
