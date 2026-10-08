import sys, json, gzip, collections
sys.path.insert(0, '/Users/dhiren/Downloads/Deccan/zen2/s3d/src')
import numpy as np, ifcopenshell, ifcopenshell.geom, ifcgen
E = json.load(gzip.open('ep000.json.gz'))[:int(sys.argv[1])]
pts = np.array([e['origin'] for e in E if e.get('origin')]); origin = np.round(np.median(pts, 0) / 10) * 10
W = ifcgen.IfcW('eq-test', origin, 'test'); tot = collections.Counter()
for e in E: tot.update(ifcgen.add_equipment(W, e))
print(dict(tot), dict(W.stats)); W.write('ifc/equip.ifc', group_cls='IfcGroup')
f = ifcopenshell.open('ifc/equip.ifc'); s = ifcopenshell.geom.settings(); s.set('use-world-coords', True)
it = ifcopenshell.geom.iterator(s, f, 4); byoid = {e['oid']: e for e in E}; err = []; errt = collections.defaultdict(list); n = 0
if it.initialize():
    while True:
        sh = it.get(); el = f.by_guid(sh.guid); n += 1
        e = byoid.get(el.Tag)
        if e and e['shapes']:
            v = np.array(sh.geometry.verts).reshape(-1, 3) + origin
            bbs = np.array([x['bbox'] for x in e['shapes'] if x.get('bbox')])
            if len(bbs):
                ref = np.concatenate([bbs[:, :3].min(0), bbs[:, 3:].max(0)])
                d = np.abs(np.concatenate([v.min(0), v.max(0)]) - ref).max(); err.append(d)
                errt[tuple(sorted({x['shape_type'].split(' ')[0] for x in e['shapes']}))[:3]].append(d)
        if not it.next(): break
err = np.array(err); print('tessellated', n, 'equipment compared', len(err), 'bbox err p50 %.4f p90 %.4f p99 %.4f within 1cm %.1f%%' % (np.percentile(err, 50), np.percentile(err, 90), np.percentile(err, 99), 100 * (err < 0.01).mean()))
for k, v in sorted(errt.items(), key=lambda kv: -len(kv[1]))[:10]:
    v = np.array(v); print(k, len(v), 'p50 %.4f p90 %.4f' % (np.percentile(v, 50), np.percentile(v, 90)))
