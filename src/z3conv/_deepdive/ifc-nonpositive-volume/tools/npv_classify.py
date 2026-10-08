#!/usr/bin/env python3
"""Classify every non-positive-volume solid of a STEP file exactly as step_check.py finds them (STEPControl_Reader,
TransferRoot per root, TopExp SOLID, GProp volume), then explain each one:
  multi_shell_nesting : solid has >1 shell, every shell alone is a positive closed solid -> OCC read-time healing grouped
                        disconnected (touching / interpenetrating) lumps of one CLOSED_SHELL into outer + 'void' shells
  inverted            : 1 shell, volume < 0, reversed volume > 0 (faces oriented inward)
  zero_flat           : |volume| ~ 0 (flat / degenerate shell)
  open_shell          : free edges present
  nan                 : volume computation failed
Also: root name, #shells, per-shell volumes. usage: npv_classify.py FILE.step OUT.json [--max-roots N]"""
import sys, json, math, argparse, collections, time
from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_SOLID, TopAbs_SHELL, TopAbs_FACE, TopAbs_EDGE
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop
from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_MakeSolid
from OCC.Core.ShapeAnalysis import ShapeAnalysis_FreeBounds
from OCC.Core.BRepCheck import BRepCheck_Analyzer
from OCC.Core.TopoDS import topods
ap = argparse.ArgumentParser(); ap.add_argument('step'); ap.add_argument('out'); ap.add_argument('--max-roots', type=int, default=0)
a = ap.parse_args()
T0 = time.time()
r = STEPControl_Reader(); assert r.ReadFile(a.step) == IFSelect_RetDone
model = r.WS().Model(); n = r.NbRootsForTransfer()
def vol(s):
    g = GProp_GProps()
    try:
        brepgprop.VolumeProperties(s, g); return g.Mass()
    except Exception:
        return float('nan')
def area(s):
    g = GProp_GProps(); brepgprop.SurfaceProperties(s, g); return g.Mass()
def items(sh, t):
    e = TopExp_Explorer(sh, t); o = []
    while e.More(): o.append(e.Current()); e.Next()
    return o
cat = collections.Counter(); ex = collections.defaultdict(list); tot = collections.Counter()
roots_npv = collections.Counter()
for i in range(1, (min(n, a.max_roots) if a.max_roots else n) + 1):
    ent = r.RootForTransfer(i)
    try:
        lab = model.StringLabel(ent).ToCString()
    except Exception:
        lab = '?'
    if not r.TransferRoot(i):
        continue
    sh = r.Shape(r.NbShapes())
    sols = items(sh, TopAbs_SOLID)
    tot['roots'] += 1; tot['solids'] += len(sols)
    tot['roots_multi_solid'] += len(sols) > 1
    for s in sols:
        shells = items(s, TopAbs_SHELL)
        tot['solids_multi_shell'] += len(shells) > 1
        v = vol(s)
        if v > 0:
            continue
        tot['npv'] += 1
        roots_npv[i] += 1
        rec = {'root': i, 'lab': lab, 'root_solids': len(sols), 'vol': v, 'shells': len(shells), 'faces': len(items(s, TopAbs_FACE))}
        if not math.isfinite(v):
            k = 'nan'
        else:
            fb = ShapeAnalysis_FreeBounds(s, 1e-3, False, False)
            free = len(items(fb.GetOpenWires(), TopAbs_EDGE)) + len(items(fb.GetClosedWires(), TopAbs_EDGE))
            rec['free_edges'] = free
            A = area(s); rec['area'] = A
            if len(shells) > 1:
                sv = []
                for shl in shells:
                    try:
                        ms = BRepBuilderAPI_MakeSolid(topods.Shell(shl)).Solid(); sv.append(vol(ms))
                    except Exception:
                        sv.append(float('nan'))
                rec['shell_vols'] = [round(x, 2) for x in sv]
                # each shell alone positive OR negative-as-void: nesting artifact if |sum of abs| > 0 and orientation of
                # the shells in the solid made the total <= 0
                k = 'multi_shell_nesting' if all(math.isfinite(x) and abs(x) > 0 for x in sv) else 'multi_shell_other'
            elif free:
                k = 'open_shell'
            elif abs(v) <= 1e-6 * max(1.0, A) ** 1.5:
                k = 'zero_flat'
            else:
                vr = vol(s.Reversed()); rec['vol_reversed'] = vr
                k = 'inverted' if vr > 0 else 'single_shell_other'
            rec['valid'] = bool(BRepCheck_Analyzer(s).IsValid())
        cat[k] += 1
        if len(ex[k]) < 8:
            ex[k].append(rec)
out = {'file': a.step, 'tot': dict(tot), 'npv_by_cause': dict(cat), 'roots_with_npv': len(roots_npv), 'examples': ex, 'sec': round(time.time() - T0, 1)}
json.dump(out, open(a.out, 'w'), indent=1)
print(json.dumps({k: out[k] for k in ('tot', 'npv_by_cause', 'roots_with_npv', 'sec')}))
