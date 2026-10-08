import glob, gzip, json, pickle, os, collections, subprocess, sys
import numpy as np
from common import *
import ifcgen, ifcjobs
ad = sorted(glob.glob(os.path.join(WORK, 'acis', 'areas', '*')), key=lambda d: -len(glob.glob(d + '/*.pkl')))[0]
area_safe = os.path.basename(ad)
geo = {}
for pf in glob.glob(ad + '/*.pkl')[:3]:
    geo.update(pickle.load(open(pf, 'rb')))
recs = [json.loads(l) for l in gzip.open(os.path.join(OUT, 'json', 'structure', area_safe + '.jsonl.gz'), 'rt')]
sel = []
for kind in ('member', 'curved_member', 'slab'):
    sel += [r for r in recs if r['kind'] == kind and r['oid'] in geo][:150]
for r in sel:
    r['_acis'] = geo[r['oid']]
pts = np.array([geo[r['oid']]['v'].mean(0) for r in sel])
W = ifcgen.IfcW('st2 test', np.round(np.median(pts, 0) / 10) * 10, area_safe)
c = collections.Counter()
for r in sel:
    e = ifcgen.add_member(W, r) if r['kind'] == 'member' else ifcgen.add_acis_object(W, r)
    c[r['kind'] + ('_ok' if e is not None else '_none')] += 1
out = '/data/s3d/tmp/st2test.ifc'; W.write(out, group_cls='IfcGroup')
print(area_safe, dict(c), dict(W.stats), os.path.getsize(out))
r = subprocess.run([os.path.join(os.path.dirname(sys.executable), 'IfcConvert'), '-y', '--no-progress', '--use-element-guids', out, '/data/s3d/tmp/st2test.glb'], capture_output=True, text=True)
import trimesh
m = trimesh.load('/data/s3d/tmp/st2test.glb', force='scene'); print('glb meshes', len(m.geometry), 'tris', sum(len(g.faces) for g in m.geometry.values()))
