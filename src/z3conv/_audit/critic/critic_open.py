# critic spot-check: are openings cut in class-1 IFC->STEP outputs? volume-set match, independent of the IFC auditor's graph.py
import sys, json, os, boto3, numpy as np, ifcopenshell, ifcopenshell.geom
from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_SOLID
from OCC.Core.GProp import GProp_GProps
try:
    from OCC.Core.BRepGProp import brepgprop
    VP = brepgprop.VolumeProperties
except Exception:
    from OCC.Core.BRepGProp import brepgprop_VolumeProperties as VP
B = 'bim-proprietary-data'; s3 = boto3.client('s3', region_name='ap-south-1')
OUT = 'cad-disk-extract/zenitude-data-3/_state/agentwork/critic-z3/'
def meshvol(sh):
    v = np.array(sh.geometry.verts).reshape(-1, 3); f = np.array(sh.geometry.faces).reshape(-1, 3)
    if len(f) == 0: return 0.0
    a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    return float(abs(np.einsum('ij,ij->i', a, np.cross(b, c)).sum() / 6.0))
res = []
for mid, ikey, skey in json.load(open('targets.json')):
    s3.download_file(B, ikey, 'in.ifc'); s3.download_file(B, skey, 'out.step')
    f = ifcopenshell.open('in.ifc')
    sc = ifcopenshell.geom.settings(); sc.set('use-world-coords', True)
    su = ifcopenshell.geom.settings(); su.set('use-world-coords', True); su.set('disable-opening-subtractions', True)
    prods = [p for p in f.by_type('IfcProduct') if getattr(p, 'HasOpenings', None) and p.Representation]
    r = STEPControl_Reader(); r.ReadFile('out.step'); r.TransferRoots(); shp = r.OneShape()
    vols = []
    e = TopExp_Explorer(shp, TopAbs_SOLID)
    while e.More():
        g = GProp_GProps(); VP(e.Current(), g); vols.append(abs(g.Mass())); e.Next()
    vols = np.array(sorted(vols))
    def hit(x):
        if x <= 0 or len(vols) == 0: return False
        return bool(np.any(np.abs(vols / x - 1) < 0.002))
    n = dict(products_with_openings=len(prods), step_solids=len(vols), cut_only=0, uncut_only=0, both=0, neither=0, small_effect=0, errors=0)
    ex = []
    for p in prods[:400]:
        try:
            vc = meshvol(ifcopenshell.geom.create_shape(sc, p)) * 1e9; vu = meshvol(ifcopenshell.geom.create_shape(su, p)) * 1e9
        except Exception as x:
            n['errors'] += 1; continue
        if vu <= 0 or abs(vu - vc) / vu < 0.005:
            n['small_effect'] += 1; continue
        hc, hu = hit(vc), hit(vu)
        k = 'both' if hc and hu else 'cut_only' if hc else 'uncut_only' if hu else 'neither'
        n[k] += 1
        if len(ex) < 5: ex.append([p.GlobalId, p.is_a(), p.Name, round(vc, 1), round(vu, 1), k])
    res.append({'id': mid, 'step_key': skey, 'counts': n, 'examples': ex})
    print(json.dumps(res[-1]), flush=True)
s3.put_object(Bucket=B, Key=OUT + 'openings_spotcheck.json', Body=json.dumps(res, indent=1).encode())
