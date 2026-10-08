"""IFC-side helpers shared by the candidate scorer and the attribution step."""
import collections, uuid as _uuid
import ifcopenshell, ifcopenshell.guid
from . import config as C


def step_name(e):
    """The PRODUCT name ifc2step writes for an element (Name, else <type>_<GlobalId>; quotes doubled, cut at 120), un-escaped."""
    nm = e.Name if getattr(e, "Name", None) else f"{e.is_a()}_{e.GlobalId}"
    return nm.replace("'", "''")[:120].replace("''", "'")


def guid_uuid(e):
    return str(_uuid.UUID(ifcopenshell.guid.expand(e.GlobalId)))


def body_items(e):
    out = []
    rep = getattr(e, "Representation", None)
    for r in (rep.Representations if rep else []):
        if r.RepresentationIdentifier in C.BODY_IDS:
            for it in r.Items:
                out += list(it.MappingSource.MappedRepresentation.Items) if it.is_a("IfcMappedItem") else [it]
    return out


def products(f):
    """Elements with a representation, in file order (the order ifc2step walks)."""
    return [e for e in f.by_type("IfcProduct") if getattr(e, "Representation", None)]


def physical(f):
    return [e for e in products(f) if e.is_a() not in C.NONPHYS]


def transcodable(e):
    """True if ifc2step's direct (no-kernel) path can take the element: faceted items with poly loops only."""
    its = body_items(e)
    if not its or not all(i.is_a() in C.TRANSCODE_ITEMS for i in its): return False
    for i in its:
        shells = ([i.Outer] if i.is_a("IfcFacetedBrep") else list(i.SbsmBoundary) if i.is_a("IfcShellBasedSurfaceModel")
                  else list(i.FbsmFaces) if i.is_a("IfcFaceBasedSurfaceModel") else [])
        for sh in shells:
            for fc in sh.CfsFaces:
                if any(not b.Bound.is_a("IfcPolyLoop") for b in fc.Bounds): return False
    return True


def source_state(e):
    """What the source element offers: code + flags. Codes: no_body, surface_model, faceted_watertight,
    faceted_open (edges not shared by exactly two faces), other_solid. Flag holed_faces: faces with inner loops."""
    its = body_items(e)
    if not its: return dict(code="no_body", holed_faces=False, items=[])
    kinds = sorted({i.is_a() for i in its})
    if set(kinds) <= C.SURFACE_ITEMS or all(i.is_a() in ("IfcPolygonalFaceSet", "IfcTriangulatedFaceSet") and getattr(i, "Closed", True) is False for i in its):
        return dict(code="surface_model", holed_faces=False, items=kinds)
    if set(kinds) <= C.FACETED_ITEMS:
        leak = holes = False
        for b in its:
            ed = collections.Counter()
            for fc in b.Outer.CfsFaces:
                holes |= len(fc.Bounds) > 1
                for bd in fc.Bounds:
                    pts = [tuple(round(x, C.POINT_ROUND) for x in q.Coordinates) for q in bd.Bound.Polygon]
                    for a, d in zip(pts, pts[1:] + pts[:1]): ed[frozenset((a, d))] += 1
            leak |= any(v != 2 for v in ed.values())
        return dict(code="faceted_open" if leak else "faceted_watertight", holed_faces=holes, items=kinds)
    return dict(code="other_solid", holed_faces=False, items=kinds)
