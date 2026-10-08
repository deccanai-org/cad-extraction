"""Joist stand-in STEP round trip: which sub-solids read back invalid. usage: joistrt.py <decode> <job> <out.json>"""
import sys, os, json, collections, tempfile
import numpy as np
sys.path.insert(0, sys.argv[1]); job = sys.argv[2]
import joist as J, to_step as T
from sds2job import read_members
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_SOLID
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs, STEPControl_Reader
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
mems, L = read_members(job)
js = [m for m in mems if T.is_joist(m)]
out = dict(joists=len(js), bad_joists=0, bad=collections.Counter(), ex=[])
def solids(sh):
    ex = TopExp_Explorer(sh, TopAbs_SOLID); r = []
    while ex.More(): r.append(ex.Current()); ex.Next()
    return r
for m in js[:400]:
    wt, basis = J.typical_weight(m.section.name, m.section.d, m.section.weight)
    sh, info = J.joist_solid(m, wt)
    if sh is None: out['bad']['not built'] += 1; continue
    f = tempfile.mktemp(suffix='.step')
    w = STEPControl_Writer(); w.Transfer(sh, STEPControl_AsIs); w.Write(f)
    r = STEPControl_Reader(); r.ReadFile(f); r.TransferRoots(); back = r.OneShape(); os.remove(f)
    S0 = solids(sh); S1 = solids(back)
    badi = [i for i, s in enumerate(S1) if not BRepCheck_Analyzer(s).IsValid()]
    pre_bad = [i for i, s in enumerate(S0) if not BRepCheck_Analyzer(s).IsValid()]
    if badi or pre_bad:
        out['bad_joists'] += 1; out['bad']['invalid after round trip'] += len(badi); out['bad']['invalid before writing'] += len(pre_bad)
        for i in badi[:2]:
            s = S1[i]; g = GProp_GProps(); BRepGProp.VolumeProperties_s(s, g); b = Bnd_Box(); BRepBndLib.Add_s(s, b)
            lo, hi = b.CornerMin(), b.CornerMax()
            from OCP.TopAbs import TopAbs_FACE
            nf = 0; e = TopExp_Explorer(s, TopAbs_FACE)
            while e.More(): nf += 1; e.Next()
            if len(out['ex']) < 12:
                out['ex'].append(dict(member=m.id, sec=m.section.name, idx=i, n=len(S1), vol_mm3=round(g.Mass(), 1), faces=nf,
                                      ext_mm=[round(hi.X() - lo.X(), 2), round(hi.Y() - lo.Y(), 2), round(hi.Z() - lo.Z(), 2)],
                                      chord=info.get('chord_angle'), web=info.get('web_bar_dia')))
json.dump(out, open(sys.argv[3], 'w'), default=str); print(json.dumps(out, default=str)[:1500])
