#!/usr/bin/env python3
"""Read a STEP file back with OpenCASCADE and report what a consumer sees."""
import sys, json, time, os

out = {"file": sys.argv[1], "bytes": os.path.getsize(sys.argv[1])}
t0 = time.time()
try:
    from OCC.Core.STEPControl import STEPControl_Reader
    from OCC.Core.IFSelect import IFSelect_RetDone
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopAbs import (TopAbs_SOLID, TopAbs_SHELL, TopAbs_FACE,
                                 TopAbs_VERTEX)
    from OCC.Core.TopoDS import TopoDS_Compound
    from OCC.Core.BRep import BRep_Builder

    r = STEPControl_Reader()
    st = r.ReadFile(sys.argv[1])
    out["read_status"] = "ok" if st == IFSelect_RetDone else "fail:%s" % st
    if st == IFSelect_RetDone:
        out["roots"] = r.NbRootsForTransfer()
        n = r.TransferRoots()
        out["transferred"] = n
        b = BRep_Builder()
        comp = TopoDS_Compound()
        b.MakeCompound(comp)
        for i in range(1, r.NbShapes() + 1):
            b.Add(comp, r.Shape(i))
        for nm, t in (("solids", TopAbs_SOLID), ("shells", TopAbs_SHELL),
                      ("faces", TopAbs_FACE), ("vertices", TopAbs_VERTEX)):
            e = TopExp_Explorer(comp, t)
            c = 0
            while e.More():
                c += 1
                e.Next()
            out[nm] = c
except Exception as ex:
    out["error"] = "%s: %s" % (type(ex).__name__, ex)
out["read_sec"] = round(time.time() - t0, 1)
print(json.dumps(out))
