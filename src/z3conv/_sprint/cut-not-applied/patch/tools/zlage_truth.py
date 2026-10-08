"""zlage_truth.py NAME RUN : old-engine contour plates / contour cuts vs Tekla's own export: our part centroid (OCC, from the decoder
IFC of pipes2/RUN/truth_NAME) vs Tekla COG (Pset_Tekla_General CogX/Y/Z), offset along the plate normal in units of t/2, by the
part_attr depth position zlage@60 (0 middle, 1 front, 2 behind) - is the 'centred on the outline plane' assumption right?"""
import sys, os, re, json, gzip, collections, numpy as np
W = '/work/agentwork/cut-not-applied'; NAME, RUN = sys.argv[1], sys.argv[2]
sys.path.insert(0, W + '/kitp3')
import db1old
from db1dec import load
import ifcopenshell, ifcopenshell.geom, ifcopenshell.guid
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop
data = load(f'{W}/truth/{NAME}.db1'); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
M, info, cut_rel = db1old.read(data, eng); byp = {m['pid']: m for m in M}
o = db1old.Old(data); I = o.I_all
RX = re.compile(rb'ID([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})')
pid2g = {}
for x in RX.finditer(data):
    v = int.from_bytes(data[x.start() - 8:x.start() - 4], 'little', signed=True); pid2g.setdefault(v, x.group(1).decode().upper().replace('-', ''))
def attr_q(a):
    for q in [int(x) for x in np.nonzero(I[8:len(I) - 400] == a)[0] + 8]:
        if data[q - 1] == 4 and 0 <= int(I[q + 4]) <= 100 and 0 <= int(I[q + 72]) <= 64 and 32 <= data[q + 124] <= 126: return q
f = ifcopenshell.open(f'{W}/truth/{NAME}.ifc'); cog = {}
for e in f.by_type('IfcElement'):
    for r in e.IsDefinedBy or []:
        if r.is_a('IfcRelDefinesByProperties') and r.RelatingPropertyDefinition.is_a('IfcPropertySet') and r.RelatingPropertyDefinition.Name == 'Pset_Tekla_General':
            q = {p.Name: float(p.NominalValue.wrappedValue) for p in r.RelatingPropertyDefinition.HasProperties if p.Name in ('CogX', 'CogY', 'CogZ')}
            if len(q) == 3: cog[ifcopenshell.guid.expand(e.GlobalId).upper().replace('-', '')] = np.array([q['CogX'], q['CogY'], q['CogZ']])
pl = json.load(gzip.open(f'{W}/pipes2/{RUN}/truth_{NAME}/convert.json.parts.json.gz', 'rt'))
gid = {p[0]: p[5] for p in pl if p[3] == 'written'}
ours = ifcopenshell.open(f'{W}/pipes2/{RUN}/truth_{NAME}/model.ifc')
S = ifcopenshell.geom.settings(); S.set('use-world-coords', True); S.set('use-python-opencascade', True)
res = collections.defaultdict(list)
for m in M:
    if m['cut'] or m['bolt'] or not m.get('old_poly') or m['pid'] not in gid: continue
    g = pid2g.get(m['pid']); tc = cog.get(g)
    q = attr_q(m['attr'])
    if tc is None or q is None: continue
    zl = int(I[q + 60])
    try:
        sh = ifcopenshell.geom.create_shape(S, ours.by_guid(gid[m['pid']])).geometry
        gp = GProp_GProps(); brepgprop.VolumeProperties(sh, gp); c = gp.CentreOfMass(); oc = np.array([c.X(), c.Y(), c.Z()]) * 1000.0
    except Exception as ex:
        continue
    xr, y = m['xr'], m['y']; z = np.cross(xr, y); useZ = m.get('form') == 2
    P = np.array([m['O'] + xr * p[0] + y * p[1] + (z * p[2] if useZ else 0) for p in m['old_poly']])
    n = np.zeros(3)
    for i in range(len(P)):
        a, b = P[i], P[(i + 1) % len(P)]; n += np.array([(a[1] - b[1]) * (a[2] + b[2]), (a[2] - b[2]) * (a[0] + b[0]), (a[0] - b[0]) * (a[1] + b[1])])
    if np.linalg.norm(n) < 1e-9: continue
    n /= np.linalg.norm(n)
    t = float(re.findall(r'[\d.]+', m['prof'])[0]) if m['prof'] else 0
    d = tc - oc; dn = float(d @ n); dt = float(np.linalg.norm(d - dn * n))
    # normal reference: the part csys z (xr x y): is Tekla's front side +z?
    res[zl].append((dn / (t / 2) if t else 0, dt, float(n @ z), m['prof']))
for zl, v in sorted(res.items()):
    a = np.array([x[0] for x in v]); dt = np.array([x[1] for x in v]); nz = np.array([x[2] for x in v])
    s = a * np.sign(nz)                 # offset along the part csys z, in t/2
    print('zlage', zl, 'plates', len(v), '| COG offset along outline normal / (t/2): median %.2f p10 %.2f p90 %.2f | along csys z / (t/2): median %.2f p10 %.2f p90 %.2f | in-plane offset median %.1f mm'
          % (np.median(a), np.percentile(a, 10), np.percentile(a, 90), np.median(s), np.percentile(s, 10), np.percentile(s, 90), np.median(dt)), collections.Counter(x[3] for x in v).most_common(3))
