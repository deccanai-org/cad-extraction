import sys, re, collections, numpy as np
sys.path.insert(0, '/work/agentwork/cut-not-applied/kitp3')
import ifcopenshell, ifcopenshell.guid, db1old
from db1dec import load
N = sys.argv[1]
data = load(f'/work/agentwork/cut-not-applied/truth/{N}.db1')
M, info, cr = db1old.read(data, 7.24); pids = np.array(sorted({m['pid'] for m in M}), np.int64)
RX = re.compile(rb'([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})')
G = [(m.start(), m.group(1).decode().upper().replace('-', '')) for m in RX.finditer(data)]
print('db1 guid strings', len(G), [g for _, g in G[:4]], 'prefix bytes', collections.Counter(data[p - 2:p] for p, _ in G).most_common(4))
f = ifcopenshell.open(f'/work/agentwork/cut-not-applied/truth/{N}.ifc')
X = {ifcopenshell.guid.expand(e.GlobalId).upper().replace('-', ''): e for e in f.by_type('IfcElement')}
print('ifc', len(X), list(X)[:4])
hit = [(p, g) for p, g in G if g in X]
print('db1 guid strings found in the IFC:', len(hit))
u8 = np.frombuffer(data, np.uint8); pos = np.array([p for p, _ in hit], np.int64)
for k in range(2, 80, 2):
    pp = pos - k; ok = pp >= 0
    v = np.zeros(len(pp), np.int64); v[ok] = u8[pp[ok][:, None] + np.arange(4)].copy().view('<i4')[:, 0]
    i = np.searchsorted(pids, v); i[i >= len(pids)] = 0; n = int((pids[i] == v).sum())
    if n > 50: print('   offset', k, 'part-id hits', n)
