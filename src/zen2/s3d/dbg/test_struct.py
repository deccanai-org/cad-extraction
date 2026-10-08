import sys, json, gzip, collections
sys.path.insert(0, '/Users/dhiren/Downloads/Deccan/zen2/s3d/src')
import numpy as np, ifcopenshell, ifcopenshell.geom, ifcgen
R = json.load(gzip.open('sp0000.json.gz'))
area = (sys.argv[1] or None) if len(sys.argv) > 1 else None
sel = [m for m in R if (area is None or m['area'] == area) and m.get('start')][:int(sys.argv[2]) if len(sys.argv) > 2 else 4000]
pts = np.array([m['start'] for m in sel]); origin = np.round(np.median(pts, 0) / 10) * 10
W = ifcgen.IfcW('struct-test', origin, 'test')
n = 0
for m in sel:
    if ifcgen.add_member(W, m) is not None: n += 1
print('members', len(sel), 'elements', n, dict(W.stats))
W.write('ifc/struct.ifc', group_cls='IfcGroup')
f = ifcopenshell.open('ifc/struct.ifc')
s = ifcopenshell.geom.settings(); s.set('use-world-coords', True)
it = ifcopenshell.geom.iterator(s, f, 4); byoid = {m['oid']: m for m in sel}
err = collections.defaultdict(list); ng = 0
if it.initialize():
    while True:
        sh = it.get(); e = f.by_guid(sh.guid); ng += 1
        v = np.array(sh.geometry.verts).reshape(-1, 3) + origin
        m = byoid[e.Tag]
        if m.get('bbox'):
            d = np.abs(np.concatenate([v.min(0), v.max(0)]) - np.array(m['bbox'])).max()
            err[(m['section']['type'], m['cardinal_point'] in (5, 8, 2, 10), m.get('mirror'))].append(d)
        if not it.next(): break
print('tessellated', ng)
allv = np.concatenate([np.array(v) for v in err.values()])
print('ALL bbox err p50 %.4f p90 %.4f p99 %.4f  within 5mm: %.1f%%' % (np.percentile(allv, 50), np.percentile(allv, 90), np.percentile(allv, 99), 100 * (allv < 0.005).mean()))
for k, v in sorted(err.items(), key=lambda kv: -len(kv[1]))[:14]:
    v = np.array(v); print(k, len(v), 'p50 %.4f p90 %.4f within5mm %.0f%%' % (np.percentile(v, 50), np.percentile(v, 90), 100 * (v < 0.005).mean()))
