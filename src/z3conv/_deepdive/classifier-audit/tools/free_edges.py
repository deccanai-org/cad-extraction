#!/usr/bin/env python3
"""Per transferred root without a solid: shells, free (boundary) edges of the shell -> is the 'closed' shell really closed?
usage: free_edges.py FILE.stp [MAX]"""
import sys
from OCP.STEPControl import STEPControl_Reader
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_SOLID, TopAbs_SHELL
from OCP.ShapeAnalysis import ShapeAnalysis_FreeBounds
from OCP.BRepCheck import BRepCheck_Analyzer

r = STEPControl_Reader(); r.ReadFile(sys.argv[1]); n = r.NbRootsForTransfer(); mx = int(sys.argv[2]) if len(sys.argv) > 2 else 10
done = 0; stats = {'roots': n, 'no_solid': 0, 'no_solid_closed': 0, 'no_solid_open': 0}
for i in range(1, n + 1):
    r.TransferRoot(i); sh = r.Shape(r.NbShapes())
    ex = TopExp_Explorer(sh, TopAbs_SOLID)
    if ex.More():
        continue
    stats['no_solid'] += 1
    fb = ShapeAnalysis_FreeBounds(sh, 1e-3, False, False)
    nfree = 0
    w = fb.GetClosedWires(); o = fb.GetOpenWires()
    from OCP.TopAbs import TopAbs_EDGE
    for comp in (w, o):
        e = TopExp_Explorer(comp, TopAbs_EDGE)
        while e.More():
            nfree += 1; e.Next()
    stats['no_solid_closed' if nfree == 0 else 'no_solid_open'] += 1
    if done < mx:
        print({'root': i, 'free_edges': nfree, 'shell_valid': BRepCheck_Analyzer(sh).IsValid()}); done += 1
print(stats)
