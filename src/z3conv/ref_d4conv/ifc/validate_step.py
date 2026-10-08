#!/usr/bin/env python3
"""Read a STEP file back with OpenCASCADE and report what a consumer sees (roots, transferred shapes,
solids/shells/faces/vertices, bounding box in the file's length unit (mm for our writers)).
usage: validate_step.py FILE.step  -> one JSON line"""
import sys, json, time, os

out = {"file": sys.argv[1], "bytes": os.path.getsize(sys.argv[1])}
t0 = time.time()
try:
    from OCC.Core.STEPControl import STEPControl_Reader
    from OCC.Core.IFSelect import IFSelect_RetDone
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopAbs import TopAbs_SOLID, TopAbs_SHELL, TopAbs_FACE, TopAbs_VERTEX
    from OCC.Core.TopoDS import TopoDS_Compound
    from OCC.Core.BRep import BRep_Builder
    from OCC.Core.Bnd import Bnd_Box

    r = STEPControl_Reader()
    st = r.ReadFile(sys.argv[1])
    out["read_status"] = "ok" if st == IFSelect_RetDone else "fail:%s" % st
    if st == IFSelect_RetDone:
        out["roots"] = r.NbRootsForTransfer()
        out["transferred"] = r.TransferRoots()
        b = BRep_Builder(); comp = TopoDS_Compound(); b.MakeCompound(comp)
        for i in range(1, r.NbShapes() + 1):
            b.Add(comp, r.Shape(i))
        for nm, t in (("solids", TopAbs_SOLID), ("shells", TopAbs_SHELL), ("faces", TopAbs_FACE), ("vertices", TopAbs_VERTEX)):
            e = TopExp_Explorer(comp, t); c = 0
            while e.More():
                c += 1; e.Next()
            out[nm] = c
        try:
            box = Bnd_Box()
            try:
                from OCC.Core.BRepBndLib import brepbndlib
                brepbndlib.Add(comp, box, False)
            except ImportError:
                from OCC.Core.BRepBndLib import brepbndlib_Add
                brepbndlib_Add(comp, box, False)
            if not box.IsVoid():
                out["bbox"] = [round(v, 3) for v in box.Get()]
        except Exception as ex:
            out["bbox_error"] = "%s: %s" % (type(ex).__name__, str(ex)[:120])
except Exception as ex:
    out["error"] = "%s: %s" % (type(ex).__name__, ex)
out["read_sec"] = round(time.time() - t0, 1)
print(json.dumps(out))
