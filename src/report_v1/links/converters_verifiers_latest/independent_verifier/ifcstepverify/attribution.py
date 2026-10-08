"""Map STEP parts to IFC elements and classify every gap:
BY_DESIGN (types skipped on purpose) | SOURCE (IFC geometry missing / open / broken) | PIPELINE (IFC fine, STEP not) | UNCLASSIFIED."""
import collections
import numpy as np
import ifcopenshell, ifcopenshell.geom
from . import config as C
from .ifcmodel import products, physical, step_name, guid_uuid, body_items, transcodable, source_state


_FRESH = {}


def _buildable(e, ifc_mesh, ifc_path):
    """Buildable if the mesh pass produced it; else try alone on a freshly opened file (create_shape on a file the
    iterator has already walked returns empty geometry)."""
    if ifc_mesh and e.GlobalId in ifc_mesh: return True
    try:
        if ifc_path not in _FRESH: _FRESH.clear(); _FRESH[ifc_path] = ifcopenshell.open(ifc_path)
        g = _FRESH[ifc_path].by_guid(e.GlobalId)
        return len(ifcopenshell.geom.create_shape(ifcopenshell.geom.settings(), g).geometry.faces) > 0
    except Exception:
        return False


def map_parts(f, scan, n_parts, ifc_mesh):
    """-> (list index part-1 -> element or None, confidence note)."""
    if scan["uuids"]:
        by = {guid_uuid(e): e for e in products(f)}
        if len(scan["uuids"]) == n_parts:
            return [by.get(u) for u in scan["uuids"]], "exact (IFC GlobalId, one part per element)"
        return [None] * n_parts, f"unavailable ({len(scan['uuids'])} GlobalIds for {n_parts} parts)"
    names = scan["product_names"]
    cand = [e for e in physical(f) if body_items(e)]
    exp = [e for e in cand if transcodable(e)] + [e for e in cand if not transcodable(e)]   # ifc2step hybrid order
    out = [None] * n_parts; n_al = 0
    for i in range(min(n_parts, len(exp), len(names))):
        if step_name(exp[i]) != names[i]: break
        out[i] = exp[i]; n_al += 1
    byname = collections.defaultdict(list)
    for e in cand: byname[step_name(e)].append(e)
    return out, (n_al, byname)


def resolve_by_position(i, names, byname, part_bbox, ifc_mesh, used):
    cs = [e for e in byname.get(names[i], []) if e.GlobalId not in used]
    if len(cs) == 1: return cs[0], "by unique name"
    if not cs or part_bbox is None: return None, "not resolved"
    c = np.array([(part_bbox[0] + part_bbox[3]) / 2, (part_bbox[1] + part_bbox[4]) / 2, (part_bbox[2] + part_bbox[5]) / 2])
    best = []
    for e in cs:
        m = ifc_mesh.get(e.GlobalId) if ifc_mesh else None
        if m: best.append((float(np.linalg.norm(np.array(m["centre_mm"]) - c)), e.GlobalId, e))
    if not best: return None, "not resolved (no IFC mesh for candidates)"
    best.sort(key=lambda x: (x[0], x[1]))
    return best[0][2], f"by name + nearest position ({best[0][0]:.1f} mm)"


def attribute(f, scan, geo, ifc_mesh, ifc_path=None):
    """-> dict(parts=[issue rows], missing=[rows], extra=int, mapping=str). Every row has cause_class + cause."""
    rows_parts, rows_missing = [], []
    n_parts = geo["summary"]["parts"] if geo and "summary" in geo else 0
    parts = geo["parts"] if geo and "parts" in geo else []
    mapping_note = "geometry not analysed"
    if parts:
        mp, info = map_parts(f, scan, n_parts, ifc_mesh)
        if isinstance(info, tuple):
            n_al, byname = info; used = {e.GlobalId for e in mp if e is not None}
            mapping_note = f"exact file order for {n_al} of {n_parts} parts, rest by name + position"
        else:
            mapping_note = info; byname = None
        for p in parts:
            if p["kind"] == "solid" and p.get("brep_valid", True): continue
            i = p["part"] - 1
            e = mp[i] if i < len(mp) else None; how = "exact"
            if e is None and byname is not None and i < len(scan["product_names"]):
                e, how = resolve_by_position(i, scan["product_names"], byname, p.get("bbox"), ifc_mesh, used)
                if e is not None: used.add(e.GlobalId)
            st = source_state(e) if e is not None else None
            mesh = (ifc_mesh or {}).get(e.GlobalId) if e is not None else None
            row = dict(step_part=p["part"], step_name=(scan["product_names"][i] if i < len(scan["product_names"]) else
                       (f"product-{scan['uuids'][i]}" if i < len(scan["uuids"]) else None)),
                       ifc_type=e.is_a() if e else None, ifc_name=e.Name if e else None, ifc_globalid=e.GlobalId if e else None,
                       match=how if e is not None else "no IFC element found", where_mm=[round(x, 1) for x in p["bbox"]] if "bbox" in p else None,
                       source_state=st["code"] if st else None, source_holed_faces=st["holed_faces"] if st else None)
            if p["kind"] == "open_shell":
                row["issue"] = "open_shell"
                if st is None: row.update(cause_class="UNCLASSIFIED", cause="open shell; the IFC element could not be identified")
                elif st["code"] in ("faceted_open", "surface_model"): row.update(cause_class="SOURCE", cause=f"IFC geometry is {st['code'].replace('_', ' ')}; copied faithfully")
                else: row.update(cause_class="PIPELINE", cause=f"IFC element is a closed solid ({st['code']}) but the STEP part is an open shell")
            elif p["kind"] == "impossible_solid":
                row.update(issue="broken_solid", step_volume_m3=p["volume_mm3"] / 1e9, own_box_m3=p["box_mm3"] / 1e9,
                           ifc_volume_m3=mesh["volume_m3"] if mesh else None)
                if mesh and mesh["impossible"]: row.update(cause_class="SOURCE", cause="the IFC element is already broken (volume > own box)")
                elif st and st["holed_faces"] and scan["writer"] == "ifc2step":
                    row.update(cause_class="PIPELINE", cause="faces with holes (tube / HSS ends) written with the hole loop winding like the outer loop")
                elif st: row.update(cause_class="PIPELINE", cause="IFC element is sound but the STEP solid is self-overlapping")
                else: row.update(cause_class="UNCLASSIFIED", cause="broken solid; the IFC element could not be identified")
            elif p["kind"] == "empty":
                row.update(issue="empty_part", cause_class="PIPELINE" if st and st["code"] != "no_body" else "UNCLASSIFIED", cause="STEP part without geometry")
            else:
                row.update(issue="brepcheck_invalid", cause_class="PIPELINE", cause="solid fails OpenCascade BRepCheck (likely non-planar polygon written as a flat face)")
            rows_parts.append(row)
    # IFC elements missing from the STEP (independent of geometry analysis)
    els = products(f)
    if scan["uuids"]:
        have = set(scan["uuids"]); miss = [e for e in els if guid_uuid(e) not in have]
        extra = len(have - {guid_uuid(e) for e in els}); conf = "exact (GlobalId)"
    else:
        cnt = collections.Counter(scan["product_names"]); byk = collections.defaultdict(list)
        for e in els: byk[step_name(e)].append(e)
        miss = []
        for k in sorted(byk):
            es = byk[k]; d = len(es) - cnt.get(k, 0)
            if d > 0:   # elements that cannot have been converted are blamed first; the rest by file order
                es = sorted(es, key=lambda e: (e.is_a() not in C.SKIP_TYPES, bool(body_items(e)), e.id()))
                miss += es[:d]
        extra = sum(max(0, cnt[k] - len(byk.get(k, []))) for k in cnt); conf = "by count per name (same-named elements are interchangeable)"
    for e in sorted(miss, key=lambda e: e.id()):
        if e.is_a() in C.SKIP_TYPES: cc, cause = "BY_DESIGN", f"{e.is_a()} is skipped by the converter on purpose"
        elif e.is_a() in C.NONPHYS: cc, cause = "BY_DESIGN", "spatial / non-physical element"
        elif not body_items(e): cc, cause = "SOURCE", "element has no body geometry"
        elif not _buildable(e, ifc_mesh, ifc_path): cc, cause = "SOURCE", "IFC geometry cannot be built (IfcOpenShell fails too)"
        else: cc, cause = "PIPELINE", "IFC geometry builds but the element is not in the STEP"
        rows_missing.append(dict(ifc_type=e.is_a(), ifc_name=e.Name, ifc_globalid=e.GlobalId, cause_class=cc, cause=cause, confidence=conf))
    return dict(parts=rows_parts, missing=rows_missing, extra_step_parts=extra, mapping=mapping_note)
