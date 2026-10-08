#!/usr/bin/env python3
"""Evidence for one part that v6.0.1 wrote at L2 (alternative source):
  exact kernel B-rep volume (no tessellation), the v6.0.1 L0/L2 meshes, the v6.1 L0 mesh, OCC verdicts for each
  (same checks as step_check), and the distance of every L2 / v6.1 vertex to the exact B-rep surface.
usage: l2_evidence.py OLD_CONV.py NEW_CONV.py IFC GUID"""
import sys, os, json, importlib.util, tempfile
import numpy as np
def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
OLD = load(sys.argv[1], 'old'); NEW = load(sys.argv[2], 'new')
import ifcopenshell, ifcopenshell.geom
from OCC.Core.BRepTools import breptools
from OCC.Core.TopoDS import TopoDS_Shape
from OCC.Core.BRep import BRep_Builder
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop
from OCC.Core.BRepExtrema import BRepExtrema_DistShapeShape
from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
from OCC.Core.gp import gp_Pnt
os.environ.setdefault('DEFLECTION', '0.005'); os.environ.setdefault('ANG_DEFLECTION', '0.6')
f = ifcopenshell.open(sys.argv[3]); g = sys.argv[4]; p = f.by_guid(g)
res = {'gid': g, 'cls': p.is_a(), 'name': p.Name}
# exact B-rep
st = ifcopenshell.geom.settings(); st.set('use-world-coords', True); st.set('iterator-output', ifcopenshell.ifcopenshell_wrapper.SERIALIZED)
sh = ifcopenshell.geom.create_shape(st, p)
brep = sh.geometry.brep_data if hasattr(sh.geometry, 'brep_data') else sh.brep_data
fn = tempfile.mktemp(suffix='.brep'); open(fn, 'w').write(brep)
exact = TopoDS_Shape(); breptools.Read(exact, fn, BRep_Builder())
gp = GProp_GProps(); brepgprop.VolumeProperties(exact, gp); res['exact_brep_volume_mm3'] = round(gp.Mass() * 1e9, 1)
def mesh_and_check(M, mode, tri=False, label=''):
    s, _, m = M.kernel_settings(mode)
    shp = ifcopenshell.geom.create_shape(s, p)
    V, faces, iids = M.kernel_geometry(shp.geometry, m)
    pieces = M.kernel_pieces(f, V, faces, iids) if hasattr(M, 'kernel_pieces') else [M.Piece(V, faces, M.kernel_role(f, faces, iids), 1)]
    rep = M.Repair(2)
    bp = M.build_part(pieces, rep, tri=tri)
    X, solids, surfaces, tags = bp
    td = tempfile.mkdtemp(); sp = M.Spool(os.path.join(td, 's.bin'), 2)
    fr = sp.emit(p.Name, g, p.is_a(), solids, surfaces, X); sp.close()
    hdr, gents = M.header_text('ev')
    out = os.path.join(td, 'p.step')
    with open(out, 'wb') as o, open(sp.path, 'rb') as s_:
        o.write(hdr.encode()); o.write(gents.encode()); o.write(s_.read()); o.write(M.TAIL.encode())
    lf = os.path.join(td, 'l.json'); of = os.path.join(td, 'o.jsonl'); json.dump([out], open(lf, 'w'))
    NEW.verify_worker(lf, of)
    r = json.loads(open(of).readline())
    ok, why = NEW.judge(r, fr)
    # vertex distance to the exact surface (sample <= 400 vertices)
    used = np.unique([i for s_ in solids + surfaces for fc in s_.faces for lp in fc for i in lp])
    idx = used[np.linspace(0, len(used) - 1, min(400, len(used))).astype(int)]
    dmax = 0.0
    for i in idx:
        x, y, z = (X[i] / 1000.0).tolist()   # exact B-rep is in metres
        d = BRepExtrema_DistShapeShape(BRepBuilderAPI_MakeVertex(gp_Pnt(x, y, z)).Vertex(), exact)
        if d.IsDone():
            dmax = max(dmax, d.Value() * 1000.0)
    return {'mesh_volume_mm3': round(fr.vol, 1), 'occ_volumes': [round(v, 1) for v in (r.get('vols') or []) if v is not None],
            'occ_valid': r.get('valid'), 'verdict': 'pass' if ok else why, 'faces': fr.nfaces, 'solids': fr.nsol,
            'max_vertex_distance_to_exact_mm': round(dmax, 4), 'repair': dict(rep.stats)}
res['v601_L0_poly'] = mesh_and_check(OLD, 'poly')
res['v601_L2_trimesh'] = mesh_and_check(OLD, 'tri')
res['v61_L0_poly'] = mesh_and_check(NEW, 'poly')
print(json.dumps(res))
