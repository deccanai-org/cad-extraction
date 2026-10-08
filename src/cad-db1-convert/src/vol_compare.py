import sys, numpy as np, collections, ifcopenshell, ifcopenshell.geom
def vols(path, only_csg=False):
    f = ifcopenshell.open(path); st = ifcopenshell.geom.settings(); st.set(st.USE_WORLD_COORDS, True)
    out = []
    for e in f.by_type('IfcBuildingElement'):
        if not e.Representation: continue
        if only_csg and not any(r.RepresentationType == 'CSG' for r in e.Representation.Representations): continue
        try: sh = ifcopenshell.geom.create_shape(st, e)
        except Exception: continue
        v = np.array(sh.geometry.verts).reshape(-1, 3); t = np.array(sh.geometry.faces).reshape(-1, 3)
        if not len(t): continue
        a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
        vol = abs(np.einsum('ij,ij->i', a, np.cross(b, c)).sum()) / 6.0
        cen = v.mean(0)
        out.append((vol, cen, e.GlobalId))
    return out
if __name__ == '__main__':
  ours = vols(sys.argv[1], only_csg=True); ref = vols(sys.argv[2])
  R = np.array([c for _, c, _ in ref]); RV = np.array([v for v, _, _ in ref])
  c = collections.Counter(); diffs = []
  for vol, cen, g in ours:
      d = np.linalg.norm(R - cen, axis=1); j = int(np.argmin(d))
      if d[j] > 50: c['no_ref_element_near'] += 1; continue
      rel = abs(vol - RV[j]) / max(RV[j], 1e-9); diffs.append(rel)
      c['vol_within_0.5%' if rel < 0.005 else ('vol_within_2%' if rel < 0.02 else 'vol_differs')] += 1
  print('cut members', len(ours), dict(c), 'median rel diff', round(float(np.median(diffs)), 5) if diffs else None)
