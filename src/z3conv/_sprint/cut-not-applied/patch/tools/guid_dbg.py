import sys, re, collections
sys.path.insert(0, '/work/agentwork/cut-not-applied/kitp2')
import ifcopenshell, ifcopenshell.guid
from db1dec import load
data = load('/work/agentwork/cut-not-applied/truth/gsk.db1')
RX = re.compile(rb'ID([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})')
G = [m.group(1).decode().upper() for m in RX.finditer(data)]
print('db1 guids', len(G), G[:5])
f = ifcopenshell.open('/work/agentwork/cut-not-applied/truth/gsk.ifc')
E = [e for e in f.by_type('IfcElement')]
X = [ifcopenshell.guid.expand(e.GlobalId).upper() for e in E]
print('ifc', len(X), X[:5], [e.GlobalId for e in E[:3]])
# tekla puts its GUID also as property? search the IFC text for one db1 guid
txt = open('/work/agentwork/cut-not-applied/truth/gsk.ifc', errors='replace').read()
for g in G[:3]:
    print(g, g in txt, g.lower() in txt)
# property sets with GUID-like values
import itertools
for e in E[:2]:
    for r in e.IsDefinedBy or []:
        if r.is_a('IfcRelDefinesByProperties'):
            pd = r.RelatingPropertyDefinition
            if pd.is_a('IfcPropertySet'):
                print(e.GlobalId, pd.Name, [(p.Name, getattr(p, 'NominalValue', None)) for p in pd.HasProperties][:12])
# compare hex digits overlap: last 12 hex of guids
s1 = {g[-12:] for g in G}; s2 = {x.replace('-', '')[-12:] for x in X}
print('last12 overlap', len(s1 & s2))
s1 = {g[:8] for g in G}; s2 = {x[:8] for x in X}
print('first8 overlap', len(s1 & s2))
