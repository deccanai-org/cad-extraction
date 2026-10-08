#!/usr/bin/env python3
"""diagnose one part: v6 L0 geometry -> mini STEP -> OCC BRepCheck statuses per sub-shape.
usage: diag_part.py CONVERTER.py IFC GUID [--tri] [--local]"""
import sys, os, collections, importlib.util, tempfile
spec = importlib.util.spec_from_file_location('v6', sys.argv[1]); V = importlib.util.module_from_spec(spec); spec.loader.exec_module(V)
import ifcopenshell, ifcopenshell.util.unit, numpy as np
f = ifcopenshell.open(sys.argv[2]); g = sys.argv[3]; tri = '--tri' in sys.argv; local = '--local' in sys.argv
sc = ifcopenshell.util.unit.calculate_unit_scale(f) * 1000
tc = V.Transcoder(f, sc); rep = V.Repair(2)
p = f.by_guid(g)
items, rid = V.body_items(p)
if local and items[0].is_a('IfcMappedItem'):
    pieces = tc.items_local(items[0].MappingSource.MappedRepresentation.Items)
else:
    pieces = tc.product(p, items)
if pieces is None:
    print('not transcodable'); sys.exit()
bp = V.build_part(pieces, rep, tri=tri)
X, solids, surfaces, tags = bp
print('part', p.is_a(), p.Name, 'pieces', len(pieces), 'solids', len(solids), 'surfaces', len(surfaces), 'tags', tags, dict(rep.stats))
for s in solids:
    print('  solid faces', len(s.faces), 'closed', s.closed, 'vol %.1f' % s.vol, 'voids', len(s.voids))
td = tempfile.mkdtemp()
sp = V.Spool(os.path.join(td, 'sp.bin'), 2)
fr = sp.emit(p.Name, g, p.is_a(), solids, surfaces, X)
sp.close()
hdr, gents = V.header_text('diag')
fn = os.path.join(td, 'one.step')
with open(fn, 'wb') as out, open(sp.path, 'rb') as s_:
    out.write(hdr.encode()); out.write(gents.encode()); out.write(s_.read()); out.write(V.TAIL.encode())
from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_SOLID, TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX, TopAbs_SHELL, TopAbs_WIRE
from OCC.Core.BRepCheck import BRepCheck_Analyzer, BRepCheck_ListIteratorOfListOfStatus
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop
r = STEPControl_Reader(); r.ReadFile(fn); r.TransferRoots(); sh = r.OneShape()
ex = TopExp_Explorer(sh, TopAbs_SOLID); k = 0
names = {0: 'NoError'}
import OCC.Core.BRepCheck as BC
for nm in dir(BC):
    if nm.startswith('BRepCheck_') and isinstance(getattr(BC, nm), int):
        names[getattr(BC, nm)] = nm
while ex.More():
    s = ex.Current(); ex.Next(); k += 1
    an = BRepCheck_Analyzer(s)
    gp = GProp_GProps(); brepgprop.VolumeProperties(s, gp)
    print('OCC solid', k, 'valid', an.IsValid(), 'vol %.1f' % gp.Mass())
    if not an.IsValid():
        cnt = collections.Counter()
        for typ, tn in ((TopAbs_SHELL, 'shell'), (TopAbs_FACE, 'face'), (TopAbs_WIRE, 'wire'), (TopAbs_EDGE, 'edge'), (TopAbs_VERTEX, 'vertex')):
            e2 = TopExp_Explorer(s, typ)
            while e2.More():
                sub = e2.Current(); e2.Next()
                res = an.Result(sub)
                if res is None:
                    continue
                it = BRepCheck_ListIteratorOfListOfStatus(res.Status())
                while it.More():
                    st = it.Value(); it.Next()
                    if st != 0:
                        cnt[(tn, names.get(st, st))] += 1
        print('   statuses', dict(cnt))
