#!/usr/bin/env python3
"""For faceted-body products with openings: kernel volume with / without opening subtraction vs the STEP part volume.
usage: faceted_openings_volume.py FILE.ifc STEP_PARTS.jsonl.gz [N]"""
import sys, os, ifcopenshell, ifcopenshell.geom as G, gzip, json, tempfile, collections
from OCC.Core.BRepTools import breptools
from OCC.Core.BRep import BRep_Builder
from OCC.Core.TopoDS import TopoDS_Shape
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop
f = ifcopenshell.open(sys.argv[1])
st = [json.loads(l) for l in gzip.open(sys.argv[2], 'rt')]
N = int(sys.argv[3]) if len(sys.argv) > 3 else 12
byname = collections.defaultdict(list)
for s in st:
    byname[s.get('name')].append(s)
L = None
def vol(inst, openings=True):
    s = G.settings(); s.set('iterator-output', ifcopenshell.ifcopenshell_wrapper.SERIALIZED)
    if not openings:
        s.set('disable-opening-subtractions', True)
    sh = G.create_shape(s, inst); p = os.path.join(tempfile.gettempdir(), 'fo_%d.brep' % os.getpid()); open(p, 'w').write(getattr(sh, 'brep_data', None) or sh.geometry.brep_data)
    x = TopoDS_Shape(); breptools.Read(x, p, BRep_Builder()); g = GProp_GProps(); brepgprop.VolumeProperties(x, g)
    return g.Mass() * 1e9          # m3 -> mm3
n = 0
for p in f.by_type('IfcProduct'):
    if not getattr(p, 'HasOpenings', None) or not p.Representation:
        continue
    items = [it for r in p.Representation.Representations if r.RepresentationIdentifier in (None, 'Body', 'Facetation') for it in r.Items]
    lf = []
    for it in items:
        lf += list(it.MappingSource.MappedRepresentation.Items) if it.is_a('IfcMappedItem') else [it]
    if not lf or not all(x.is_a() in ('IfcFacetedBrep', 'IfcFacetedBrepWithVoids', 'IfcShellBasedSurfaceModel', 'IfcFaceBasedSurfaceModel', 'IfcPolygonalFaceSet', 'IfcTriangulatedFaceSet') for x in lf):
        continue
    try:
        vo = vol(p, True); vn = vol(p, False)
    except Exception as e:
        print(p.Name, 'kernel error', e); continue
    sv = [round(c.get('volume') or 0) for c in byname.get(p.Name) or []]
    print(p.is_a(), p.Name, 'openings', len(p.HasOpenings), 'kernel_no_open', round(vn), 'kernel_with_open', round(vo), 'ratio', round(vo / vn, 4), 'STEP same-name vols', sv[:4])
    n += 1
    if n >= N:
        break
