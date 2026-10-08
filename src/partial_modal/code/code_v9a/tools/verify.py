#!/usr/bin/env python3
"""Rebuild every part of a model from its schedules (steelbuild) and compare it with the delivered STEP part of the same
id and with the exact source geometry: volume, centroid and bounding box. Writes verification.csv +
verification_summary.json into the schedule folder.

usage: verify.py SCHEDULE_DIR DELIVERED.step [--ifc SOURCE.ifc] [--jobs N] [--parts id,id]

The source reference (--ifc) is every product of the IFC as the IfcOpenShell kernel evaluates it (srcbrep.py, world
coordinates, no faceting). Solids the kernel returns are measured as they are. Faceted B-reps (IfcFacetedBrep,
IfcFacetedBrepWithVoids, IfcPolygonalFaceSet, ...) come back from the kernel as loose faces: the faces of each
representation item (one compound of the kernel's output) are sewn into shells (0.001 mm: the facets share their
vertices), every shell is checked for free edges, a closed shell becomes a solid and a closed shell inside another one is
its void. Every solid is measured on its own and the results are summed (never one compound: BRepGProp skips an open
solid inside a compound without notice). A part whose source still has an open shell after sewing has no source volume
to compare against: source_check 'source_open', counted separately, never measured. source_kind says what the source
was for each part: 'solid' (kernel solids), 'sewn' (faceted, sewn here), 'solid+sewn', 'open', 'none' (the kernel
produced no geometry for the product); source_reference names the same as the reference the source check used:
kernel_solid | sewn_faces | kernel_solid+sewn_faces | source_open | none.

The IFC is the authoritative geometry: the source check holds every part to it (TOL_SRC_* for parametric parts,
TOL_GRID_* for parts rebuilt from faces). The delivered STEP was written by IfcOpenShell from the same IFC (curved faces
as facets, coordinates on a 0.01 mm grid): wherever a closed source reference exists - kernel solids or faceted faces
sewn here - the delivered check allows the delivered file's own deviation from that source on top of its tolerances
(delivered_facet_dev_vol_rel / _centroid_mm / _bbox_mm; delivered_within_allowance_only = 'yes' where a part passes only
through that allowance). faces_source (exact and recovered parts, from exact.py's exact_sources.csv) says where the faces
the part was rebuilt or recovered from came from: 'ifc' (the IFC's own faceted geometry at full precision) or
'delivered_step' (the delivered STEP's faces, 0.01 mm grid). For the 'ifc' ones, raw_ifc_* (information only) compare the
rebuilt part with the polyhedra of the IFC's own polygons as extract.py read them from the IFC entities (exact_ifc.jsonl),
measured by the divergence theorem: a reference neither IfcOpenShell's geometry kernel nor OpenCASCADE produced
(verification_summary.json kernel_free_reference).

Pass / fail tolerances are absolute (TOL_* below). Every absolute deviation column has a scale-relative companion
(`*_rel` = deviation / size_mm, the diagonal of the reference part's bounding box) for reading; the relative columns
change no status.
"""
import argparse, csv, json, math, os, sys, time, traceback
from concurrent.futures import ProcessPoolExecutor
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'kit'))

# tolerances against the delivered model: its curved faces are stored as flat facets and its coordinates on a 0.01 mm
# grid, so a parametric part differs from it by the facet chords only
TOL_VOL_REL = 0.01      # 1 % of the part volume
TOL_CEN = 1.0           # mm
TOL_BBOX = 1.0          # mm
# against the exact source geometry (IfcOpenShell kernel, no faceting): parametric parts must coincide
TOL_SRC_VOL, TOL_SRC_CEN, TOL_SRC_BBOX = 1e-3, 0.05, 0.05
# parts rebuilt from the delivered faceted geometry carry its 0.01 mm coordinate grid
TOL_GRID_VOL, TOL_GRID_CEN, TOL_GRID_BBOX = 0.01, 0.05, 0.02
# sewing the loose faces of a faceted source item: its facets share their vertices exactly, this only joins equal points
SEW_TOL_M = 1e-6        # m (the kernel's output unit) = 0.001 mm, the builder's own facet sewing tolerance


# ======================================================================================== measuring solids
def _ancestor_map():
    """an indexed map shape -> list of ancestor shapes (OCP version safe)"""
    try:
        from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape          # OCP < 7.8
        return TopTools_IndexedDataMapOfShapeListOfShape()
    except ImportError:
        from OCP.collections import IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher
        return IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher()


def edge_use(shape):
    """(free, non-manifold) edge counts of a shape's faces: an edge bounded by one face only is free (an open shell's
    boundary), one shared by more than two faces is non-manifold; degenerate edges and the seams of closed surfaces
    (one face on both sides) are not free"""
    from OCP.TopExp import TopExp
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCP.BRep import BRep_Tool
    from OCP.TopoDS import TopoDS
    edg = TopoDS.Edge_s if hasattr(TopoDS, 'Edge_s') else TopoDS.Edge
    m = _ancestor_map()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, m)   # a seam lists its face twice
    free = multi = 0
    for i in range(1, m.Extent() + 1):
        if BRep_Tool.Degenerated_s(edg(m.FindKey(i))):
            continue
        n = sum(1 for _ in m.FindFromIndex(i))
        if n == 1:
            free += 1
        elif n > 2:
            multi += 1
    return free, multi


def _props(solids):
    """volume, volume-weighted centre and combined bounding box of a list of solids, each measured on its own"""
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    vol, mom = 0.0, np.zeros(3)
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    for s in solids:
        g = GProp_GProps()
        BRepGProp.VolumeProperties_s(s.wrapped, g)
        v = g.Mass()
        c = g.CentreOfMass()
        vol += v
        mom += v * np.array([c.X(), c.Y(), c.Z()])
        bb = s.bounding_box(optimal=True)
        lo = np.minimum(lo, [bb.min.X, bb.min.Y, bb.min.Z])
        hi = np.maximum(hi, [bb.max.X, bb.max.Y, bb.max.Z])
    if not solids:
        return vol, np.zeros(3), np.zeros(3), np.zeros(3)
    return vol, (mom / vol if abs(vol) > 1e-12 else np.zeros(3)), lo, hi


def open_solids(solids):
    """how many of the solids have a shell with free edges (not closed: no volume is defined for them)"""
    return sum(1 for s in solids if edge_use(s.wrapped)[0])


def n_shells(solids):
    """shells of all the solids: the bodies (lumps) and voids a part consists of, however they are grouped into solids
    (a STEP file stores a solid with two disjoint lumps as two solids)"""
    from OCP.TopAbs import TopAbs_SHELL
    return sum(len(_children(s.wrapped, TopAbs_SHELL)) for s in solids)


# ======================================================================================== the part-level checks
def _diff(v, c, lo, hi, r):
    rv, rc, rlo, rhi = r['v'], np.array(r['c']), np.array(r['lo']), np.array(r['hi'])
    return (abs(v - rv) / max(abs(rv), 1e-9), float(np.linalg.norm(c - rc)),
            float(max(np.max(np.abs(lo - rlo)), np.max(np.abs(hi - rhi)))))


def _size(r):
    """size of a part: the diagonal of its bounding box, mm"""
    return float(np.linalg.norm(np.array(r['hi'], float) - np.array(r['lo'], float)))


def _rel(x, size):
    return f'{x / size:.2e}' if size > 0 else ''


def check(geometry, v, c, lo, hi, ref, src, scale=1.0):
    """the part checks of one measured part (volume v, centre c, bounding box lo..hi; mm) against the delivered part `ref`
    and the exact source `src` ({'v', 'c', 'lo', 'hi'}, either None; a source with 'open' set has no volume): the
    deviation columns of verification.csv plus source_check / delivered_check. verify.py runs it on the in-memory rebuild,
    e2e.py on the parts of the STEP file build_model.py writes, read back, and recover.py on every candidate it would
    accept, with `scale` < 1 (each pass / fail limit times scale: stricter, never looser; verify.py and e2e.py use 1).

    The IFC is the authoritative geometry. The source check holds the part to the source within the TOL_SRC_* (parametric)
    or TOL_GRID_* (exact / recovered) limits. The delivered STEP was written from the same IFC by IfcOpenShell, with its
    curved faces as facets and its coordinates on a 0.01 mm grid, so wherever a closed source reference exists (kernel
    solids, or a faceted source's faces sewn here) the delivered check allows the delivered file's own deviation from that
    source on top of TOL_VOL_REL / TOL_CEN / TOL_BBOX (delivered_facet_dev_*: the allowance; delivered_within_allowance_only
    'yes' where the part passes only through it). Without a closed source the delivered check is the plain tolerance."""
    c, lo, hi = np.asarray(c, float), np.asarray(lo, float), np.asarray(hi, float)
    row = {}
    closed_src = src is not None and not src.get('open')
    size = _size(ref) if ref is not None else (_size(src) if closed_src else float(np.linalg.norm(hi - lo)))
    row['size_mm'] = round(size, 3)
    tight = geometry == 'parametric'
    if closed_src:
        sv, sc_, sb = _diff(v, c, lo, hi, src)
        tv, tc, tb = (TOL_SRC_VOL, TOL_SRC_CEN, TOL_SRC_BBOX) if tight else (TOL_GRID_VOL, TOL_GRID_CEN, TOL_GRID_BBOX)
        row.update(s_v=round(src['v'], 3), s_cx=round(src['c'][0], 4), s_cy=round(src['c'][1], 4), s_cz=round(src['c'][2], 4),
                   s_lo=' '.join(f'{x:.4f}' for x in src['lo']), s_hi=' '.join(f'{x:.4f}' for x in src['hi']))
        row.update(src_vol_rel_diff=f'{sv:.2e}', src_centroid_diff_mm=round(sc_, 5), src_centroid_diff_rel=_rel(sc_, size),
                   src_bbox_diff_mm=round(sb, 5), src_bbox_diff_rel=_rel(sb, size),
                   source_check='exact' if (sv <= scale * tv and sc_ <= scale * tc and sb <= scale * tb) else 'DIFFERS')
    elif src is not None:
        row.update(source_check='source_open')     # the source surface is not closed: it has no volume to compare
    else:
        row.update(source_check='n/a')
    if ref is not None:
        dv, dc, db = _diff(v, c, lo, hi, ref)
        # the delivered file's own deviation from the closed source reference (kernel solids or sewn faceted faces)
        fv, fc, fb = 0.0, 0.0, 0.0
        if closed_src:
            fv = abs(src['v'] - ref['v']) / max(abs(ref['v']), 1e-9)
            fc = float(np.linalg.norm(np.array(src['c']) - np.array(ref['c'])))
            fb = float(max(np.max(np.abs(np.array(src['lo']) - np.array(ref['lo']))), np.max(np.abs(np.array(src['hi']) - np.array(ref['hi'])))))
        ok = dv <= scale * (TOL_VOL_REL + fv) and dc <= scale * (TOL_CEN + fc) and db <= scale * (TOL_BBOX + fb)
        plain = dv <= scale * TOL_VOL_REL and dc <= scale * TOL_CEN and db <= scale * TOL_BBOX
        row.update(d_cx=round(ref['c'][0], 4), d_cy=round(ref['c'][1], 4), d_cz=round(ref['c'][2], 4),
                   d_lo=' '.join(f'{x:.4f}' for x in ref['lo']), d_hi=' '.join(f'{x:.4f}' for x in ref['hi']))
        row.update(delivered_volume=round(ref['v'], 3), vol_rel_diff=f'{dv:.2e}', centroid_diff_mm=round(dc, 4),
                   centroid_diff_rel=_rel(dc, size), bbox_diff_mm=round(db, 4), bbox_diff_rel=_rel(db, size),
                   delivered_facet_dev_vol_rel=f'{fv:.2e}', delivered_facet_dev_centroid_mm=round(fc, 4),
                   delivered_facet_dev_bbox_mm=round(fb, 4), delivered_check='match' if ok else 'DIFFERS',
                   delivered_within_allowance_only='yes' if ok and not plain else '')
    return row


# what the source reference of a part is (verification.csv source_reference), from the kind of its source B-rep
SOURCE_REFERENCE = {'solid': 'kernel_solid', 'sewn': 'sewn_faces', 'solid+sewn': 'kernel_solid+sewn_faces',
                    'open': 'source_open', 'none': 'none', 'error': 'error'}


def part_status(row, n_invalid):
    """status of a part from its checks: 'match' needs the delivered check and every source check that can be made"""
    if not row.get('delivered_check'):
        return 'no_delivered_part'
    ok = row['delivered_check'] == 'match' and row.get('source_check') in ('exact', 'n/a', 'source_open')
    if n_invalid:
        return 'INVALID_SOLID'      # a solid that fails BRepCheck would be dropped by STEP writers
    return 'match' if ok else 'MISMATCH'


_SCHED = None
_REF = None
_SRC = None


def _init(folder, ref, src):
    global _SCHED, _REF, _SRC
    import steelbuild
    _SCHED = steelbuild.Schedules(folder)
    _REF = ref
    _SRC = src


def _one(part):
    import steelbuild
    t0 = time.time()
    pid = part['part_id']
    row = dict(part_id=pid, ifc_class=part['ifc_class'], role=part['role'], geometry=part['geometry'])
    ref = _REF.get(pid)
    src = _SRC.get(pid)
    if src is not None:
        row.update(source_kind=src['kind'], source_reference=SOURCE_REFERENCE.get(src['kind'], src['kind']),
                   src_solids=src['n_solids'], src_open_shells=src['n_open'], src_free_edges=src['free_edges'],
                   src_sheets=src.get('sheets', 0))
    else:
        row.update(source_kind='none', source_reference='none' if _SRC else '')
    src = source_reference(src)
    try:
        solids = steelbuild.build_part(part, _SCHED)
        n_invalid = sum(1 for x in solids if not x.is_valid)
        row['invalid_solids'] = n_invalid
        row['open_solids'] = open_solids(solids)
        v, c, lo, hi = _props(solids)
        row.update(n_solids=len(solids), n_shells=n_shells(solids), volume=round(v, 3), cx=round(c[0], 4), cy=round(c[1], 4), cz=round(c[2], 4),
                   lo=' '.join(f'{x:.4f}' for x in lo), hi=' '.join(f'{x:.4f}' for x in hi))
        row.update(check(part['geometry'], v, c, lo, hi, ref, src))
        row['status'] = part_status(row, n_invalid)
    except Exception as e:
        row.update(status='BUILD_ERROR', error=f'{type(e).__name__}: {e}')
    row['seconds'] = round(time.time() - t0, 3)
    return row


def source_reference(src):
    """a part's entry of source_props as check() takes it: the closed reference ('v', 'c', 'lo', 'hi' in mm), or the
    entry with 'open' set when its surface is not closed (no volume: never measured), or None (no source geometry)"""
    if src is None or src.get('v') is not None:
        return src
    return dict(src, open=True) if src.get('n_open') else None


# ======================================================================================== the source reference
def _faces_in(shape, solids, groups):
    """split one product's kernel B-rep into its solids and its groups of loose faces (the faces of one compound = one
    representation item, or of one shell outside any solid)"""
    from OCP.TopoDS import TopoDS_Iterator
    from OCP.TopAbs import TopAbs_SOLID, TopAbs_SHELL, TopAbs_FACE, TopAbs_COMPOUND, TopAbs_COMPSOLID
    t = shape.ShapeType()
    if t == TopAbs_SOLID:
        return
    if t == TopAbs_FACE:
        groups.append([shape])
        return
    if t == TopAbs_SHELL:
        groups.append(_children(shape, TopAbs_FACE))
        return
    if t in (TopAbs_COMPOUND, TopAbs_COMPSOLID):
        loose = []
        it = TopoDS_Iterator(shape)
        while it.More():
            ch = it.Value()
            if ch.ShapeType() == TopAbs_FACE:
                loose.append(ch)
            else:
                _faces_in(ch, solids, groups)
            it.Next()
        if loose:
            groups.append(loose)


def _children(shape, kind):
    from OCP.TopExp import TopExp_Explorer
    out = []
    ex = TopExp_Explorer(shape, kind)
    while ex.More():
        out.append(ex.Current())
        ex.Next()
    return out


def _is_sheet(faces):
    """all faces of an item lie in one plane (within the sewing tolerance): they bound no volume - a stray surface, not a
    body. The builder skips such face sets in the same way (steelbuild._is_sheet)"""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    from OCP.TopAbs import TopAbs_VERTEX
    from OCP.BRep import BRep_Tool
    from OCP.TopoDS import TopoDS
    fce = TopoDS.Face_s if hasattr(TopoDS, 'Face_s') else TopoDS.Face
    vtx = TopoDS.Vertex_s if hasattr(TopoDS, 'Vertex_s') else TopoDS.Vertex
    best, area = None, -1.0
    for f in faces:
        ad = BRepAdaptor_Surface(fce(f))
        if ad.GetType() != GeomAbs_Plane:
            return False
        g = GProp_GProps()
        BRepGProp.SurfaceProperties_s(f, g)
        if g.Mass() > area:
            best, area = ad.Plane(), g.Mass()
    o, n = best.Location(), best.Axis().Direction()
    for f in faces:
        for v in _children(f, TopAbs_VERTEX):
            p = BRep_Tool.Pnt_s(vtx(v))
            if abs((p.X() - o.X()) * n.X() + (p.Y() - o.Y()) * n.Y() + (p.Z() - o.Z()) * n.Z()) > SEW_TOL_M:
                return False
    return True


def _sew(faces):
    """sew the loose faces of one source item: (closed shells, number of open shells or faces left, their free edges)"""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Sewing
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_SHELL, TopAbs_FACE
    from OCP.ShapeFix import ShapeFix_Shell
    from OCP.TopoDS import TopoDS
    shl = TopoDS.Shell_s if hasattr(TopoDS, 'Shell_s') else TopoDS.Shell
    sew = BRepBuilderAPI_Sewing(SEW_TOL_M)
    for fc in faces:
        sew.Add(fc)
    sew.Perform()
    sewn = sew.SewedShape()
    closed, n_open, free_edges = [], 0, 0
    ex = TopExp_Explorer(sewn, TopAbs_SHELL)
    while ex.More():
        fx = ShapeFix_Shell(shl(ex.Current()))
        fx.Perform()
        for sh in _children(fx.Shape(), TopAbs_SHELL):
            sh = shl(sh)
            fr, _ = edge_use(sh)
            if fr:
                n_open += 1
                free_edges += fr
            else:
                closed.append(sh)
        ex.Next()
    ex = TopExp_Explorer(sewn, TopAbs_FACE, TopAbs_SHELL)     # faces the sewing left on their own
    while ex.More():
        n_open += 1
        free_edges += edge_use(ex.Current())[0]
        ex.Next()
    return closed, n_open, free_edges


def _solids_of_shells(shells):
    """closed shells of one item -> [(solid, sign)]: every shell (its faces consistently oriented by ShapeFix_Shell) made
    a solid facing outward - positive volume, the shell reversed when the source lists its facets inward (ShapeFix_Solid
    is not used: far from the origin it can turn a large solid inside out). A shell is the void of another solid (sign
    -1) only when it lies entirely inside it: its bounding box within that solid's and every one of its vertices inside.
    Shells that merely overlap (a bolt's head and shank) are bodies of their own and are summed, as the delivered file,
    the builder and the source polygons count them."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.TopAbs import TopAbs_IN, TopAbs_VERTEX
    from OCP.BRep import BRep_Tool
    from OCP.TopoDS import TopoDS
    from build123d import Solid
    vtx = TopoDS.Vertex_s if hasattr(TopoDS, 'Vertex_s') else TopoDS.Vertex
    shl = TopoDS.Shell_s if hasattr(TopoDS, 'Shell_s') else TopoDS.Shell

    def solid(sh):
        so = BRepBuilderAPI_MakeSolid(sh).Solid()
        g = GProp_GProps()
        BRepGProp.VolumeProperties_s(so, g)
        if g.Mass() < 0:                                  # inside out: the same shell, reversed
            so = BRepBuilderAPI_MakeSolid(shl(sh.Reversed())).Solid()
        return so

    def box(sh):
        b = Bnd_Box()
        BRepBndLib.Add_s(sh, b)
        lo, hi = b.CornerMin(), b.CornerMax()
        return (lo.X(), lo.Y(), lo.Z(), hi.X(), hi.Y(), hi.Z())
    single = [solid(sh) for sh in shells]
    if len(single) == 1:
        return [(Solid(single[0]), 1.0)]
    boxes = [box(sh) for sh in shells]
    pts = [[BRep_Tool.Pnt_s(vtx(v)) for v in _children(sh, TopAbs_VERTEX)] for sh in shells]
    within = lambda a, b: all(a[k] >= b[k] for k in range(3)) and all(a[k] <= b[k] for k in range(3, 6))
    inside = set()
    for j in range(len(shells)):
        for i, so in enumerate(single):
            if i == j or i in inside or not within(boxes[j], boxes[i]):
                continue
            if all(BRepClass3d_SolidClassifier(so, p, SEW_TOL_M).State() == TopAbs_IN for p in pts[j]):
                inside.add(j)
                break
    return [(Solid(so), -1.0 if j in inside else 1.0) for j, so in enumerate(single)]


def _brep_props(fn):
    from OCP.BRepTools import BRepTools
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Shape
    from OCP.TopAbs import TopAbs_SOLID
    from build123d import Solid
    shape = TopoDS_Shape()
    BRepTools.Read_s(shape, fn, BRep_Builder())
    solids = [Solid(s) for s in _children(shape, TopAbs_SOLID)]
    groups = []
    _faces_in(shape, solids, groups)
    sewn, n_open, free_edges, sheets = [], 0, 0, 0
    for g in groups:
        if _is_sheet(g):
            sheets += 1
            continue
        closed, no, fe = _sew(g)
        n_open += no
        free_edges += fe
        if closed:
            sewn += _solids_of_shells(closed)
    kind = ('open' if n_open else ('solid+sewn' if solids and sewn else 'sewn' if sewn else 'solid' if solids else 'none'))
    out = {'kind': kind, 'n_solids': len(solids) + sum(1 for _, sg in sewn if sg > 0), 'n_voids': sum(1 for _, sg in sewn if sg < 0),
           'n_open': n_open, 'free_edges': free_edges, 'sheets': sheets}
    if n_open or not (solids or sewn):
        return out                                   # no volume to compare: never measured
    v, c, lo, hi = _props(solids)                    # the kernel's own solids exactly as before
    if sewn:
        mom = v * c if solids else np.zeros(3)
        lo, hi = (lo, hi) if solids else (np.full(3, np.inf), np.full(3, -np.inf))
        for so, sg in sewn:
            sv, sc, slo, shi = _props([so])
            v += sg * sv
            mom = mom + sg * sv * sc
            if sg > 0:
                lo, hi = np.minimum(lo, slo), np.maximum(hi, shi)
        c = mom / v if abs(v) > 1e-30 else np.zeros(3)
    out.update(v=v * 1e9, c=(c * 1e3).tolist(), lo=(lo * 1e3).tolist(), hi=(hi * 1e3).tolist())
    return out


def _brep_one(arg):
    guid, fn = arg
    try:
        return guid, _brep_props(fn)
    except Exception as e:
        import traceback
        tb = traceback.extract_tb(e.__traceback__)[-1]
        return guid, {'kind': 'error', 'n_solids': 0, 'n_open': 0, 'free_edges': 0, 'sheets': 0,
                      'error': f'{type(e).__name__} at line {tb.lineno}: {e}'}


# kernel threads of the source pass, whatever --jobs: the B-rep of every product does not depend on it, and the kernel's
# log (its product-less message counts follow the per-thread caches) is then the same for every run
SRCBREP_THREADS = 8


def source_props(ifc_path, workdir, jobs=8, keep_log=True, only=None):
    """exact geometry of every product as the IfcOpenShell kernel evaluates the IFC (the kernel that produced the
    delivered model, here without faceting): {GlobalId: {'kind', 'n_solids', 'n_open', 'free_edges', and when closed
    'v', 'c', 'lo', 'hi' in mm}}. keep_log: the kernel's log of the run and its B-rep census go into workdir
    (source_kernel_log.jsonl, source_brep_census.csv: tools/reference_defects.py reads them); otherwise they are discarded
    with the B-rep files. only: measure just these GlobalIds (the kernel still evaluates the whole model)"""
    import subprocess, tempfile, shutil
    d = tempfile.mkdtemp(prefix='_srcbrep_', dir=workdir)
    log = os.path.join(workdir if keep_log else d, 'source_kernel_log.jsonl')
    try:
        subprocess.run([sys.executable, os.path.join(HERE, 'srcbrep.py'), ifc_path, d, str(SRCBREP_THREADS), '--log', log],
                       check=True, stdout=subprocess.DEVNULL)
        idx = json.load(open(os.path.join(d, 'index.json')))
        work = [(g, os.path.join(d, fn)) for g, fn in idx.items() if only is None or g in only]
        with ProcessPoolExecutor(jobs) as ex:
            res = dict(ex.map(_brep_one, work, chunksize=8))
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return res


def _run_parts(parts, jobs, initargs):
    """rebuild + compare in worker processes; a part that crashes its worker (native OpenCASCADE fault) is isolated by
    re-running smaller groups and reported as BUILD_CRASH instead of losing the model's results"""
    from concurrent.futures.process import BrokenProcessPool
    try:
        with ProcessPoolExecutor(min(jobs, max(1, len(parts))), initializer=_init, initargs=initargs) as ex:
            return list(ex.map(_one, parts, chunksize=4 if len(parts) > 64 else 1))
    except BrokenProcessPool:
        if len(parts) == 1:
            p = parts[0]
            return [dict(part_id=p['part_id'], ifc_class=p['ifc_class'], role=p['role'], geometry=p['geometry'],
                         status='BUILD_CRASH', error='native crash while building or measuring this part')]
        n = max(1, len(parts) // 8)
        out = []
        for i in range(0, len(parts), n):
            out += _run_parts(parts[i:i + n], jobs, initargs)
        return out


def raw_ifc_props(folder, want):
    """a reference without any geometry kernel, for the parts rebuilt or recovered from the IFC's own faces
    (exact_sources.csv faces_source 'ifc'): volume, centre and bounding box of the polyhedra the IFC's polygons state -
    exact_ifc.jsonl, which extract.py reads straight from the IFC entities (placements and the length unit applied) -
    by the divergence theorem (stepfacets.mass); bodies that bound no volume are skipped as the builder skips them.
    Neither IfcOpenShell's geometry kernel nor OpenCASCADE produced it: {part id: {'v', 'c', 'lo', 'hi'}}"""
    import stepfacets, steelbuild
    fn = os.path.join(folder, 'exact_ifc.jsonl')
    out = {}
    if not want or not os.path.exists(fn):
        return out
    for line in open(fn):
        if not line.strip():
            continue
        r = json.loads(line)
        if r['part_id'] not in want:
            continue
        bodies = [s for s in r['solids'] if not steelbuild._is_sheet(s['faces'])]
        if not bodies:
            continue
        v, c, lo, hi = stepfacets.mass([{'outer': s['faces'], 'voids': s.get('voids', [])} for s in bodies])
        out[r['part_id']] = dict(v=float(v), c=[float(x) for x in c], lo=[float(x) for x in lo], hi=[float(x) for x in hi])
    return out


def delivered_props(step_path):
    import stepfacets
    m = stepfacets.Model(step_path)
    out = {}
    for pid, d in m.products().items():
        v, c, lo, hi = stepfacets.mass(d['solids'])
        out[pid] = {'v': v, 'c': c.tolist(), 'lo': lo.tolist(), 'hi': hi.tolist(), 'name': d['name']}
    return out


COLS = ['part_id', 'ifc_class', 'role', 'geometry', 'status', 'source_check', 'delivered_check', 'n_solids', 'invalid_solids',
        'open_solids', 'n_shells', 'volume', 'delivered_volume', 'size_mm',
        'src_vol_rel_diff', 'src_centroid_diff_mm', 'src_centroid_diff_rel', 'src_bbox_diff_mm', 'src_bbox_diff_rel',
        'vol_rel_diff', 'centroid_diff_mm', 'centroid_diff_rel', 'bbox_diff_mm', 'bbox_diff_rel',
        'delivered_facet_dev_bbox_mm', 'delivered_facet_dev_vol_rel', 'delivered_facet_dev_centroid_mm',
        'delivered_within_allowance_only', 'cx', 'cy', 'cz', 'lo', 'hi', 'd_cx', 'd_cy', 'd_cz', 'd_lo', 'd_hi',
        's_v', 's_cx', 's_cy', 's_cz', 's_lo', 's_hi', 'source_kind', 'source_reference', 'faces_source', 'src_solids',
        'src_open_shells', 'src_free_edges', 'src_sheets', 'raw_ifc_vol_rel_diff', 'raw_ifc_centroid_diff_mm',
        'raw_ifc_bbox_diff_mm', 'seconds', 'error']


def coverage(rows):
    """how many parts were checked against which reference, per geometry kind (the honest denominator of every claim)"""
    from collections import Counter
    n = len(rows)
    src_checked = sum(1 for r in rows if r.get('source_check') in ('exact', 'DIFFERS'))
    del_checked = sum(1 for r in rows if r.get('delivered_check') in ('match', 'DIFFERS'))
    both = sum(1 for r in rows if r.get('source_check') in ('exact', 'DIFFERS') and r.get('delivered_check') in ('match', 'DIFFERS'))
    geo = sorted({r['geometry'] for r in rows})
    return dict(parts=n, checked_against_source=src_checked, checked_against_delivered=del_checked, checked_against_both=both,
                source_checked_pct=round(100.0 * src_checked / n, 2) if n else None,
                not_checked_against_source=dict(Counter(r.get('source_check') or r['status'] for r in rows if r.get('source_check') not in ('exact', 'DIFFERS'))),
                source_kind=dict(Counter(r.get('source_kind', '') for r in rows)),
                source_reference=dict(Counter(r.get('source_reference', '') for r in rows)),
                by_faces_source={fs: dict(parts=sum(1 for r in rows if r.get('faces_source') == fs),
                                          checked_against_source=sum(1 for r in rows if r.get('faces_source') == fs and r.get('source_check') in ('exact', 'DIFFERS')),
                                          source_check=dict(Counter(r.get('source_check', '') for r in rows if r.get('faces_source') == fs)),
                                          status=dict(Counter(r['status'] for r in rows if r.get('faces_source') == fs)))
                                 for fs in sorted({r['faces_source'] for r in rows if r.get('faces_source')})},
                by_geometry={g: dict(parts=sum(1 for r in rows if r['geometry'] == g),
                                     checked_against_source=sum(1 for r in rows if r['geometry'] == g and r.get('source_check') in ('exact', 'DIFFERS')),
                                     source_check=dict(Counter(r.get('source_check', '') for r in rows if r['geometry'] == g)))
                             for g in geo})


def kernel_free(rows):
    """the kernel-free cross-check (raw_ifc_* columns) summed up: how many parts, the largest deviations, how many lie
    within the faceted source tolerances (TOL_GRID_*)"""
    R = [r for r in rows if r.get('raw_ifc_centroid_diff_mm') not in (None, '')]
    mx = lambda k: max((float(r[k]) for r in R), default=None)
    within = sum(1 for r in R if float(r['raw_ifc_vol_rel_diff']) <= TOL_GRID_VOL and float(r['raw_ifc_centroid_diff_mm']) <= TOL_GRID_CEN
                 and float(r['raw_ifc_bbox_diff_mm']) <= TOL_GRID_BBOX)
    return dict(parts=len(R), within_source_faceted_tolerances=within, max_vol_rel=mx('raw_ifc_vol_rel_diff'),
                max_centroid_mm=mx('raw_ifc_centroid_diff_mm'), max_bbox_mm=mx('raw_ifc_bbox_diff_mm'),
                note="the rebuilt part against the polyhedra of the IFC's own polygons (exact_ifc.jsonl, read from the IFC entities "
                     "without a geometry kernel; divergence theorem) for the parts whose faces were taken from the IFC (faces_source "
                     "ifc): a reference neither IfcOpenShell's kernel nor OpenCASCADE produced; information only, no status depends on it")


def failures(rows):
    """every part that is not a match, with the deviations that failed and their scale-relative size"""
    out = []
    for r in rows:
        if r['status'] == 'match':
            continue
        out.append({k: r.get(k) for k in ('part_id', 'geometry', 'role', 'status', 'source_check', 'delivered_check', 'size_mm',
                                          'vol_rel_diff', 'centroid_diff_mm', 'centroid_diff_rel', 'bbox_diff_mm', 'bbox_diff_rel',
                                          'src_vol_rel_diff', 'src_centroid_diff_mm', 'src_centroid_diff_rel', 'src_bbox_diff_mm',
                                          'src_bbox_diff_rel', 'invalid_solids', 'open_solids', 'n_solids', 'source_reference',
                                          'faces_source', 'error') if r.get(k) not in (None, '')})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('folder')
    ap.add_argument('step')
    ap.add_argument('--jobs', type=int, default=os.cpu_count())
    ap.add_argument('--parts', default='')
    ap.add_argument('--ifc', default='')
    a = ap.parse_args()
    t0 = time.time()
    ref = delivered_props(a.step)
    src = source_props(a.ifc, a.folder, a.jobs) if a.ifc else {}
    import steelbuild
    parts = steelbuild.Schedules(a.folder).parts
    if a.parts:
        want = set(a.parts.split(','))
        parts = [p for p in parts if p['part_id'] in want]
    rows = _run_parts(parts, a.jobs, (a.folder, ref, src))
    # where the faces of the exact / recovered parts came from (exact.py's exact_sources.csv: the source IFC at full
    # precision 'ifc', or the delivered STEP 'delivered_step'; recover.py keeps the file, so a recovered part still
    # names the faces it was recovered from)
    fs = os.path.join(a.folder, 'exact_sources.csv')
    fsrc = {r['part_id']: r['faces_source'] for r in csv.DictReader(open(fs, newline='', encoding='utf-8'))} if os.path.exists(fs) else {}
    for r in rows:
        if r.get('geometry') != 'parametric' and r['part_id'] in fsrc:
            r['faces_source'] = fsrc[r['part_id']]
    # the kernel-free cross-check of those parts (information: no status depends on it)
    raw = raw_ifc_props(a.folder, {r['part_id'] for r in rows if r.get('faces_source') == 'ifc'})
    for r in rows:
        x = raw.get(r['part_id'])
        if x is None or r.get('volume') in (None, ''):
            continue
        dv, dc, db = _diff(float(r['volume']), np.array([float(r['cx']), float(r['cy']), float(r['cz'])]),
                           np.array([float(t) for t in r['lo'].split()]), np.array([float(t) for t in r['hi'].split()]), x)
        r.update(raw_ifc_vol_rel_diff=f'{dv:.2e}', raw_ifc_centroid_diff_mm=round(dc, 5), raw_ifc_bbox_diff_mm=round(db, 5))
    built = {r['part_id'] for r in rows}
    missing = [pid for pid in ref if pid not in built]
    with open(os.path.join(a.folder, 'verification.csv'), 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow(r)
    from collections import Counter
    rel = lambda k: max((float(r[k]) for r in rows if r.get(k) not in (None, '')), default=None)
    summ = dict(parts=len(rows), delivered_parts=len(ref), delivered_parts_not_built=len(missing),
                status=dict(Counter(r['status'] for r in rows)),
                status_by_geometry={g: dict(Counter(r['status'] for r in rows if r['geometry'] == g)) for g in ('parametric', 'recovered', 'exact')},
                source_check=dict(Counter(r.get('source_check', '') for r in rows)), delivered_check=dict(Counter(r.get('delivered_check', '') for r in rows)),
                source_reference_parts=sum(1 for s in src.values() if s.get('v') is not None),
                source_reference=dict(Counter(r['source_reference'] for r in rows if r.get('source_reference'))),
                faces_source=dict(Counter(r['faces_source'] for r in rows if r.get('faces_source'))),
                delivered_within_allowance_only=sum(1 for r in rows if r.get('delivered_within_allowance_only') == 'yes'),
                kernel_free_reference=kernel_free(rows),
                source_coverage=coverage(rows) if src else dict(parts=len(rows), checked_against_source=0, note='no --ifc: no source reference'),
                invalid_solids=sum(int(r.get('invalid_solids') or 0) for r in rows), open_solids=sum(int(r.get('open_solids') or 0) for r in rows),
                max_relative_deviation=dict(centroid_vs_delivered=rel('centroid_diff_rel'), bbox_vs_delivered=rel('bbox_diff_rel'),
                                            centroid_vs_source=rel('src_centroid_diff_rel'), bbox_vs_source=rel('src_bbox_diff_rel'),
                                            note='deviation / size_mm (diagonal of the reference part bounding box); informative, no status depends on it'),
                not_matching=failures(rows),
                tolerances=dict(delivered=dict(volume_rel=TOL_VOL_REL, centroid_mm=TOL_CEN, bbox_mm=TOL_BBOX, plus='the delivered file\'s own deviation from the closed source reference (kernel solids or sewn faceted faces), where one exists'), source_parametric=dict(volume_rel=TOL_SRC_VOL, centroid_mm=TOL_SRC_CEN, bbox_mm=TOL_SRC_BBOX), source_faceted=dict(volume_rel=TOL_GRID_VOL, centroid_mm=TOL_GRID_CEN, bbox_mm=TOL_GRID_BBOX)), seconds=round(time.time() - t0, 1))
    json.dump(summ, open(os.path.join(a.folder, 'verification_summary.json'), 'w'), indent=1)
    print(json.dumps({k: v for k, v in summ.items() if k != 'not_matching'}, indent=1))


if __name__ == '__main__':
    main()
