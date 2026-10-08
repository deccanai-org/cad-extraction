import sys, json, numpy as np, collections, ifcopenshell, ifcopenshell.geom, ifcopenshell.util.element as ue
f = ifcopenshell.open(sys.argv[1]); st = ifcopenshell.geom.settings(); st.set(st.USE_WORLD_COORDS, True)
n = 0; seen = collections.Counter()
for e in f.by_type('IfcBeam') + f.by_type('IfcMechanicalFastener') + f.by_type('IfcDiscreteAccessory'):
    prof = None
    try:
        ps = ue.get_psets(e)
        for k, v in ps.items():
            for kk, vv in v.items():
                if kk.lower() in ('profile', 'profilename', 'profile_name') and isinstance(vv, str): prof = vv
    except Exception: pass
    nm = (prof or e.ObjectType or e.Name or '')
    if 'STUD' not in nm.upper(): continue
    key = nm
    seen[key] += 1
    if seen[key] > 2: continue
    sh = ifcopenshell.geom.create_shape(st, e); V = np.array(sh.geometry.verts).reshape(-1, 3) * 1000
    c = V.mean(0); U, S, Wt = np.linalg.svd(V - c); ax = Wt[0]
    t = (V - c) @ ax; R = V - c - np.outer(t, ax)
    # axis line through the centre of the bounding cylinder: use mid of extremes in two perpendicular dirs
    p1 = Wt[1]; p2 = Wt[2]; a1 = R @ p1; a2 = R @ p2; off = np.array([(a1.max() + a1.min()) / 2, (a2.max() + a2.min()) / 2])
    rad = np.linalg.norm(np.stack([a1, a2], 1) - off, axis=1)
    tt = np.round(t - t.min(), 2); rr = np.round(rad, 2)
    prs = sorted(set(zip(tt.tolist(), rr.tolist())))
    print(key, e.is_a(), 'L', round(float(t.max() - t.min()), 2), 'nverts', len(V), 'distinct t', sorted(set(tt.tolist()))[:12], 'radii', sorted(set(rr.tolist()))[-6:])
print(seen.most_common(10))
