import sys, json, re
import numpy as np
import ifcopenshell, ifcopenshell.geom, ifcopenshell.util.element as UE
f = ifcopenshell.open(sys.argv[1])
pts_in = [np.array(x) for x in json.loads(sys.argv[2])]     # SDS2 work points (inches), to locate the members
st = ifcopenshell.geom.settings(); st.set("use-world-coords", True)
rows = []
for e in f.by_type("IfcProduct"):
    if not e.is_a("IfcBeam") and not e.is_a("IfcMember") and not e.is_a("IfcColumn"): continue
    txt = " ".join(str(x) for x in (e.Name, e.ObjectType, getattr(e, "Description", None), getattr(e, "Tag", None)))
    if not re.search(r"HSS ?6 ?X ?4 ?X ?1/2", txt.upper()): continue
    items = []
    if e.Representation:
        for r in e.Representation.Representations:
            for it in r.Items:
                items.append(it.is_a() + (":" + it.MappingSource.MappedRepresentation.Items[0].is_a() if it.is_a("IfcMappedItem") else ""))
    try:
        sh = ifcopenshell.geom.create_shape(st, e)
        v = np.array(sh.geometry.verts).reshape(-1, 3); fc = np.array(sh.geometry.faces).reshape(-1, 3)
        a, b, c = v[fc[:, 0]], v[fc[:, 1]], v[fc[:, 2]]
        vol = float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6)
        vin = v / 0.0254                                     # geometry in metres -> inches
        lo, hi = vin.min(0), vin.max(0)
        d = [float(np.linalg.norm(vin - p, axis=1).min()) for p in pts_in]
        # principal length and centreline estimate
        cc = vin.mean(0); _, _, vt = np.linalg.svd(vin - cc, full_matrices=False); t = (vin - cc) @ vt[0]
        rows.append(dict(id=e.GlobalId, cls=e.is_a(), name=e.Name, otype=e.ObjectType, tag=getattr(e, "Tag", None), items=items,
                         vol_in3=round(abs(vol) / 0.0254 ** 3, 1), bbox_in=[round(x, 2) for x in list(lo) + list(hi)],
                         ext_in=[round(x, 2) for x in (hi - lo)], principal_len_in=round(float(np.ptp(t)), 2),
                         dist_to_pts_in=[round(x, 2) for x in d]))
    except Exception as ex:
        rows.append(dict(id=e.GlobalId, name=e.Name, items=items, err=repr(ex)))
print("n HSS6x4x1/2 products", len(rows))
for r in sorted(rows, key=lambda r: min(r.get("dist_to_pts_in") or [1e9]))[:12]:
    print(json.dumps(r))
# properties of the nearest few
for r in sorted(rows, key=lambda r: min(r.get("dist_to_pts_in") or [1e9]))[:4]:
    e = f.by_guid(r["id"]); ps = UE.get_psets(e)
    print(r["id"], json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "id"} for k, v in ps.items()})[:1200])
