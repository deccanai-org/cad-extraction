"""occ_detail.py STEP OUT.json [--roots 1,5,..] : per transferred root: solids, BRepCheck validity, volume, faces, bbox;
for every INVALID solid: shell closure / orientation (BRepCheck_Shell), per-face wire checks (BRepCheck_Face), free edges
(ShapeAnalysis_FreeBounds), self-intersection (BOPAlgo_ArgumentAnalyzer), degenerate / tiny faces."""
import sys, json, re, collections, time
from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_SOLID, TopAbs_FACE, TopAbs_SHELL, TopAbs_WIRE, TopAbs_EDGE
from OCC.Core.BRepCheck import BRepCheck_Analyzer, BRepCheck_Shell, BRepCheck_Face
from OCC.Core.TopoDS import topods
from OCC.Core.GProp import GProp_GProps
from OCC.Core.Bnd import Bnd_Box
try:
    from OCC.Core.BRepGProp import brepgprop
    VOL = brepgprop.VolumeProperties; SURF = brepgprop.SurfaceProperties
except Exception:
    from OCC.Core.BRepGProp import brepgprop_VolumeProperties as VOL, brepgprop_SurfaceProperties as SURF
try:
    from OCC.Core.BRepBndLib import brepbndlib
    BND = brepbndlib.Add
except Exception:
    from OCC.Core.BRepBndLib import brepbndlib_Add as BND
NAMES = ['NoError', 'InvalidPointOnCurve', 'InvalidPointOnCurveOnSurface', 'InvalidPointOnSurface', 'No3DCurve', 'Multiple3DCurve', 'Invalid3DCurve',
         'NoCurveOnSurface', 'InvalidCurveOnSurface', 'InvalidCurveOnClosedSurface', 'InvalidSameRangeFlag', 'InvalidSameParameterFlag',
         'InvalidDegeneratedFlag', 'FreeEdge', 'InvalidMultiConnexity', 'InvalidRange', 'EmptyWire', 'RedundantEdge', 'SelfIntersectingWire',
         'NoSurface', 'InvalidWire', 'RedundantWire', 'IntersectingWires', 'InvalidImbricationOfWires', 'EmptyShell', 'RedundantFace',
         'InvalidImbricationOfShells', 'UnorientableShape', 'NotClosed', 'NotConnected', 'SubshapeNotInShape', 'BadOrientation',
         'BadOrientationOfSubshape', 'InvalidPolygonOnTriangulation', 'InvalidToleranceValue', 'EnclosedRegion', 'CheckFail']


def sname(x):
    if isinstance(x, int):
        return NAMES[x] if 0 <= x < len(NAMES) else str(x)
    s = str(x); return s.split('.')[-1].replace('BRepCheck_', '')


def explore(sh, t):
    e = TopExp_Explorer(sh, t); out = []
    while e.More(): out.append(e.Current()); e.Next()
    return out


def detail(s):
    st = collections.Counter()
    for shl in explore(s, TopAbs_SHELL):
        cs = BRepCheck_Shell(topods.Shell(shl))
        st['shell_closed:' + sname(cs.Closed(False))] += 1
        try: st['shell_orientation:' + sname(cs.Orientation(False))] += 1
        except Exception: pass
    faces = explore(s, TopAbs_FACE); badf = 0; tiny = 0; inner = 0
    for f in faces:
        g = GProp_GProps(); SURF(f, g)
        if g.Mass() < 1e-2: tiny += 1
        nw = len(explore(f, TopAbs_WIRE)); inner += nw > 1
        if not BRepCheck_Analyzer(f).IsValid():
            badf += 1; cf = BRepCheck_Face(topods.Face(f))
            for nm, fn in (('intersect_wires', cf.IntersectWires), ('classify_wires', cf.ClassifyWires), ('orientation_of_wires', cf.OrientationOfWires)):
                try: st['face_' + nm + ':' + sname(fn(False))] += 1
                except Exception as e: st['face_' + nm + ':err'] += 1
    r = {'faces': len(faces), 'faces_invalid': badf, 'faces_tiny_lt_0.01mm2': tiny, 'faces_with_inner_loops': inner, 'status': dict(st)}
    try:
        from OCC.Core.ShapeAnalysis import ShapeAnalysis_FreeBounds
        fb = ShapeAnalysis_FreeBounds(s)
        r['free_edges'] = len(explore(fb.GetClosedWires(), TopAbs_EDGE)) + len(explore(fb.GetOpenWires(), TopAbs_EDGE))
    except Exception as e:
        r['free_edges'] = f'err {type(e).__name__}'
    try:
        from OCC.Core.BOPAlgo import BOPAlgo_ArgumentAnalyzer
        aa = BOPAlgo_ArgumentAnalyzer(); aa.SetShape1(s)
        mode = None
        for setter in ('SetSelfInterMode', 'SetSmallEdgeMode'):
            if hasattr(aa, setter):
                getattr(aa, setter)(True); mode = 'set'
        aa.Perform(); r['bop_faulty'] = bool(aa.HasFaulty()); r['bop_modes'] = mode
    except Exception as e:
        r['bop_faulty'] = f'err {type(e).__name__}'
    return r


def main():
    path, outp = sys.argv[1], sys.argv[2]
    roots = None
    if '--roots' in sys.argv:
        roots = {int(x) for x in sys.argv[sys.argv.index('--roots') + 1].split(',') if x}
    t0 = time.time()
    rd = STEPControl_Reader(); assert rd.ReadFile(path) == IFSelect_RetDone
    n = rd.NbRootsForTransfer(); out = []
    for i in range(1, n + 1):
        if roots and i not in roots:
            continue
        rd.TransferRoot(i); sh = rd.Shape(rd.NbShapes())
        sols = explore(sh, TopAbs_SOLID)
        rec = {'root': i, 'solids': len(sols), 'valid': 0, 'items': []}
        for s in sols:
            ok = BRepCheck_Analyzer(s).IsValid(); rec['valid'] += ok
            g = GProp_GProps(); VOL(s, g)
            b = Bnd_Box(); BND(s, b); xmn, ymn, zmn, xmx, ymx, zmx = b.Get()
            it = {'valid': bool(ok), 'vol': round(g.Mass(), 2), 'bbox': [round(v, 2) for v in (xmn, ymn, zmn, xmx, ymx, zmx)]}
            if not ok:
                it.update(detail(s))
            rec['items'].append(it)
        out.append(rec)
    json.dump({'file': path, 'roots_total': n, 'sec': round(time.time() - t0, 1), 'roots': out}, open(outp, 'w'))


if __name__ == '__main__':
    main()
