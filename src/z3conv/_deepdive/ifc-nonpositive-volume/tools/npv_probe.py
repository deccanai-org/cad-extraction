#!/usr/bin/env python3
"""Per-solid probe of a STEP file, same OCC read path as step_check.py (STEPControl_Reader, TransferRoot per root).
For every solid: OCC volume (GProp), BRepCheck validity, #faces, free edges (open shell?), shell count,
whether the solid bbox is flat (zero thickness), OCC classifier 'infinite point inside' (inside-out), volume after
reversing / ShapeFix_Solid. usage: npv_probe.py FILE.step OUT.jsonl [--only-bad]"""
import sys, json, math, argparse
from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_SOLID, TopAbs_FACE, TopAbs_SHELL, TopAbs_IN, TopAbs_OUT, TopAbs_ON
from OCC.Core.BRepCheck import BRepCheck_Analyzer
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib
from OCC.Core.ShapeAnalysis import ShapeAnalysis_FreeBounds, ShapeAnalysis_Shell
from OCC.Core.BRepClass3d import BRepClass3d_SolidClassifier
from OCC.Core.ShapeFix import ShapeFix_Solid
from OCC.Core.TopoDS import topods
ap = argparse.ArgumentParser(); ap.add_argument('step'); ap.add_argument('out'); ap.add_argument('--only-bad', action='store_true')
a = ap.parse_args()
r = STEPControl_Reader(); st = r.ReadFile(a.step); assert st == IFSelect_RetDone
model = r.WS().Model()
n = r.NbRootsForTransfer()
def vol(s):
    g = GProp_GProps()
    try:
        brepgprop.VolumeProperties(s, g); return g.Mass()
    except Exception:
        return float('nan')
def cnt(sh, t):
    e = TopExp_Explorer(sh, t); k = 0
    while e.More(): k += 1; e.Next()
    return k
fo = open(a.out, 'w'); tot = dict(roots=n, solids=0, npv=0)
from collections import Counter
kinds = Counter()
for i in range(1, n + 1):
    ent = r.RootForTransfer(i)
    lab = model.StringLabel(ent).ToCString()
    ok = r.TransferRoot(i)
    if not ok: continue
    sh = r.Shape(r.NbShapes())
    ex = TopExp_Explorer(sh, TopAbs_SOLID); sols = []
    while ex.More(): sols.append(ex.Current()); ex.Next()
    for k, s in enumerate(sols):
        tot['solids'] += 1
        v = vol(s)
        bad = not (v > 0)
        if bad: tot['npv'] += 1
        if a.only_bad and not bad: continue
        rec = {'root': i, 'lab': lab, 'k': k, 'nsol': len(sols), 'vol': v, 'valid': bool(BRepCheck_Analyzer(s).IsValid()),
               'faces': cnt(s, TopAbs_FACE), 'shells': cnt(s, TopAbs_SHELL)}
        b = Bnd_Box(); brepbndlib.Add(s, b, False); bb = b.Get()
        ext = [bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]]; rec['ext'] = [round(x, 3) for x in ext]
        # area
        g = GProp_GProps(); brepgprop.SurfaceProperties(s, g); rec['area'] = g.Mass()
        fb = ShapeAnalysis_FreeBounds(s, 1e-3, False, False)
        oe = fb.GetOpenWires(); ce = fb.GetClosedWires()
        rec['free_open_wires'] = cnt(oe, 6) if not oe.IsNull() else 0   # TopAbs_EDGE=6
        rec['free_closed_wires_edges'] = cnt(ce, 6) if not ce.IsNull() else 0
        try:
            c = BRepClass3d_SolidClassifier(s); c.PerformInfinitePoint(1e-6); rec['inf_state'] = int(c.State())
        except Exception as e:
            rec['inf_state'] = str(e)[:40]
        rs = s.Reversed(); rec['vol_reversed'] = vol(rs)
        try:
            sf = ShapeFix_Solid(topods.Solid(s)); sf.Perform(); rec['vol_shapefix'] = vol(sf.Solid())
        except Exception as e:
            rec['vol_shapefix'] = str(e)[:40]
        rec['ratio_absvol_area_x_minext'] = (abs(v) / (rec['area'] * max(1e-9, sorted(ext)[0]))) if rec['area'] else None
        fo.write(json.dumps(rec) + '\n')
print(json.dumps(tot))
