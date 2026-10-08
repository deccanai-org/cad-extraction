"""occ_check.py FILE.step [--detail]: per root (product): solids, BRepCheck validity, volume (same calls as step_check.py, OCP binding);
--detail: BRepCheck status of every failing sub-shape of invalid solids + shell closure / free edges"""
import sys, re, json, collections
from OCP.STEPControl import STEPControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.TopExp import TopExp_Explorer, TopExp
from OCP.TopAbs import TopAbs_SOLID, TopAbs_FACE, TopAbs_SHELL, TopAbs_EDGE, TopAbs_VERTEX, TopAbs_WIRE
from OCP.BRepCheck import BRepCheck_Analyzer, BRepCheck_NoError
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
from OCP.ShapeAnalysis import ShapeAnalysis_Shell
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
path = sys.argv[1]; detail = '--detail' in sys.argv
names = {}
txt = open(path, encoding='latin-1').read()
for m in re.finditer(r"#(\d+)\s*=\s*PRODUCT\s*\(\s*'((?:[^']|'')*)'\s*,\s*'((?:[^']|'')*)'", txt):
    names[int(m.group(1))] = (m.group(2), m.group(3))
r = STEPControl_Reader(); assert r.ReadFile(path) == IFSelect_RetDone
out = []
for i in range(1, r.NbRootsForTransfer() + 1):
    r.TransferRoot(i); sh = r.Shape(r.NbShapes())
    ex = TopExp_Explorer(sh, TopAbs_SOLID); sols = []
    while ex.More(): sols.append(ex.Current()); ex.Next()
    rec = {'root': i, 'solids': len(sols), 'valid': 0, 'vols': []}
    for s in sols:
        an = BRepCheck_Analyzer(s); ok = an.IsValid(); rec['valid'] += ok
        g = GProp_GProps(); BRepGProp.VolumeProperties_s(s, g); v = g.Mass()
        nf = 0; e2 = TopExp_Explorer(s, TopAbs_FACE)
        while e2.More(): nf += 1; e2.Next()
        b = Bnd_Box(); BRepBndLib.Add_s(s, b); mn, mx = b.CornerMin(), b.CornerMax(); bb = [round(x, 2) for x in (mn.X(), mn.Y(), mn.Z(), mx.X(), mx.Y(), mx.Z())]
        info = {'valid': ok, 'vol': round(v, 2), 'faces': nf, 'bbox': bb}
        if detail and not ok:
            from OCP.BRepCheck import BRepCheck_Shell, BRepCheck_Face, BRepCheck_Wire
            from OCP.TopoDS import TopoDS
            st = collections.Counter(); small = 0
            e3 = TopExp_Explorer(s, TopAbs_SHELL)
            while e3.More():
                shl = TopoDS.Shell(e3.Current()); cs = BRepCheck_Shell(shl)
                st['shell_closed:' + str(cs.Closed(False)).split('_')[-1]] += 1
                st['shell_orient:' + str(cs.Orientation(False)).split('_')[-1]] += 1
                e3.Next()
            e3 = TopExp_Explorer(s, TopAbs_FACE); nbadf = 0
            while e3.More():
                fc = TopoDS.Face(e3.Current())
                g2 = GProp_GProps(); BRepGProp.SurfaceProperties_s(fc, g2)
                if g2.Mass() < 1e-3: small += 1
                if not BRepCheck_Analyzer(fc).IsValid():
                    nbadf += 1; cf = BRepCheck_Face(fc)
                    for nm_, x in (('intersect_wires', cf.IntersectWires(False)), ('classify_wires', cf.ClassifyWires(False)), ('orient_wires', cf.OrientationOfWires(False))):
                        st[nm_ + ':' + str(x).split('_')[-1]] += 1
                    e4 = TopExp_Explorer(fc, TopAbs_WIRE)
                    while e4.More():
                        w = TopoDS.Wire(e4.Current()); cw = BRepCheck_Wire(w)
                        st['wire_closed:' + str(cw.Closed(False)).split('_')[-1]] += 1
                        e4.Next()
                e3.Next()
            sa = ShapeAnalysis_Shell(); sa.LoadShells(s); bad_or = sa.CheckOrientedShells(s, True)
            info['status'] = dict(st); info['invalid_faces'] = nbadf; info['faces_area_lt_1e-3'] = small
            info['bad_orientation_or_free_edges'] = bool(bad_or); info['has_free_edges'] = bool(sa.HasFreeEdges())
        rec['vols'].append(info)
    out.append(rec)
print(json.dumps(out))
