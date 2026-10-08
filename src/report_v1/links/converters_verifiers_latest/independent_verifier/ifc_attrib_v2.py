#!/usr/bin/env python3
"""Cause attribution for the problem parts of an IFC -> STEP conversion, after the census / STEP join (ported from
ifc-step-verifier ifcmodel.source_state + attribution._buildable; z3v-2026-10-02b).

usage: ifc_attrib.py SRC SRC_PARTS.jsonl.gz STEP_PARTS.jsonl.gz OUT.json [--max-surface 20000] [--max-missing 500] [--unpack-dir D]
       SRC = the job's input_key object as stored (zip / gzip / SPF; unpacked + schema-fixed like ifc/worker.py)
       (src_parts = ifc_census --parts, step_parts = step_check --parts; runs in either ifcopenshell env, no OCC)

1. STEP parts that read back without a solid (grade_join surface_parts), paired with their source element by GlobalId:
   source state of the element's body items (verifier rule, unchanged):
     surface_model  only IfcShellBasedSurfaceModel / IfcFaceBasedSurfaceModel / IfcOpenShell items, or face sets with Closed = False
     faceted_open   IfcFacetedBrep(WithVoids) whose edges are not all shared by exactly two faces (points rounded to 6 decimals)
     faceted_watertight / other_solid / no_body
   -> cause 'source' for surface_model / faceted_open (copied faithfully), else 'pipeline'.
2. Source parts missing from the STEP: IfcOpenShell builds the element alone (iterator include=[e], world coordinates) with and
   without opening subtractions:
     voided         empty with openings, non-empty without, and one of its IfcOpeningElements covers the element's whole
                    extent (0.5 mm tolerance): the source cuts the element away -> source_element_fully_voided (cause source)
     cut_empty      empty with openings, non-empty without, no single opening covers it -> pipeline (kept as missing)
     buildable      non-empty with openings -> pipeline (the converter lost it)
     not_buildable  empty even without openings -> pipeline (conservative: our converter uses the same kernel)
     no_body        no body representation -> source
v2 (main 2026-10-02): the open-shell source test first applies ifc2step6 6.1.x's repair chain at --prec 2, which adds no face:
vertices welded to the 0.01 mm grid, duplicate faces / contact walls removed, one side of a double-sided mesh kept, seam vertices
sewn within 0.1 mm (kept only if open edges decrease), T-junctions split (<= 0.02 mm); then closure on free edges. The chain is
applied to every shell (6.1.x sews only solid / closed-shell roles; the attribution asks what the converter can close).
  faceted_open              free edges remain after T-junction resolution          -> source (real free edges)
  faceted_sew_closed        closed after seam sewing (<= 0.1 mm)                   -> pipeline (the converter should make a solid)
  faceted_tjunction_closed  closed only after the T-junction split                 -> pipeline
  faceted_watertight        closed as welded (no free edge; non-manifold edges allowed) -> pipeline
  surface_model             surface-model items (rule 2: source); sub-state surface_model_open / surface_model_closed (same
                            closure test on its poly-loop shells): open -> source, closed -> pipeline (default since main
                            2026-10-02; --closed-surface-models source restores rule 2's original reading)
  state_v1 (the verifier's plain shared-edge test) is kept per part for comparison.
Prints / writes one JSON document."""
import sys, os, json, gzip, time, argparse, collections

VERSION = "ifc_attrib_v2 z3v-2026-10-02e"
BODY_IDS = (None, "Body", "Facetation")
SURFACE_ITEMS = frozenset({"IfcShellBasedSurfaceModel", "IfcFaceBasedSurfaceModel", "IfcOpenShell"})
FACETED_ITEMS = frozenset({"IfcFacetedBrep", "IfcFacetedBrepWithVoids"})
POINT_ROUND = 6
COVER_TOL_M = 0.0005


def load(p):
    with gzip.open(p, "rt") as f:
        return [json.loads(l) for l in f if l.strip()]


def body_items(e):
    out = []
    rep = getattr(e, "Representation", None)
    for r in (rep.Representations if rep else []):
        if r.RepresentationIdentifier in BODY_IDS:
            for it in r.Items:
                out += list(it.MappingSource.MappedRepresentation.Items) if it.is_a("IfcMappedItem") else [it]
    return out


def source_state(e):
    """ifc-step-verifier ifcmodel.source_state (unchanged)"""
    its = body_items(e)
    if not its: return dict(code="no_body", holed_faces=False, items=[])
    kinds = sorted({i.is_a() for i in its})
    if set(kinds) <= SURFACE_ITEMS or all(i.is_a() in ("IfcPolygonalFaceSet", "IfcTriangulatedFaceSet") and getattr(i, "Closed", True) is False for i in its):
        return dict(code="surface_model", holed_faces=False, items=kinds)
    if set(kinds) <= FACETED_ITEMS:
        leak = holes = False
        for b in its:
            ed = collections.Counter()
            for fc in b.Outer.CfsFaces:
                holes |= len(fc.Bounds) > 1
                for bd in fc.Bounds:
                    pts = [tuple(round(x, POINT_ROUND) for x in q.Coordinates) for q in bd.Bound.Polygon]
                    for a, d in zip(pts, pts[1:] + pts[:1]): ed[frozenset((a, d))] += 1
            leak |= any(v != 2 for v in ed.values())
        return dict(code="faceted_open" if leak else "faceted_watertight", holed_faces=holes, items=kinds)
    return dict(code="other_solid", holed_faces=False, items=kinds)


def _set(st, name, const, val):
    """settings across IfcOpenShell builds: 0.8 / 0.9 take the string name, 0.7 the constant"""
    try: st.set(name, val)
    except Exception: st.set(getattr(st, const), val)


QS = 100.0                      # ifc2step6 --prec 2: grid steps per mm (0.01 mm)
TOL_T = 2.0 / QS                # ifc2step6 Repair.tol_t: T-junction vertex on edge (mm)


def _weld(face_pts, scale):
    """faces [[loop [(x,y,z) file units]]] -> (faces as vertex-id loops, X (n,3) mm) on the 0.01 mm grid (ifc2step6 weld)"""
    import numpy as np
    vid = {}; Q = []; faces = []
    for f in face_pts:
        nf = []
        for lp in f:
            ids = []
            for p in lp:
                k = (int(round(p[0] * scale * QS)), int(round(p[1] * scale * QS)), int(round(p[2] * scale * QS)))
                i = vid.get(k)
                if i is None:
                    i = vid[k] = len(Q); Q.append(k)
                if not ids or ids[-1] != i: ids.append(i)
            if len(ids) > 1 and ids[0] == ids[-1]: ids.pop()
            if len(ids) >= 3: nf.append(ids)
        if nf: faces.append(nf)
    return faces, (np.array(Q, dtype=float) / QS if Q else np.zeros((0, 3)))


def _edge_counts(faces):
    c = collections.Counter()
    for f in faces:
        for lp in f:
            for j in range(len(lp)):
                a, b = lp[j], lp[(j + 1) % len(lp)]
                c[(a, b) if a < b else (b, a)] += 1
    return c


def _tjunctions(faces, X, tol=TOL_T):
    """port of ifc2step6 Repair.tjunctions: split boundary edges at boundary vertices lying on them (no faces added)"""
    import numpy as np, math
    cnt = _edge_counts(faces)
    bnd = [(fi, lp[j], lp[(j + 1) % len(lp)]) for fi, f in enumerate(faces) for lp in f for j in range(len(lp))
           if cnt[(min(lp[j], lp[(j + 1) % len(lp)]), max(lp[j], lp[(j + 1) % len(lp)]))] == 1]
    if not bnd: return faces, 0
    bv = np.unique(np.array([v for _, a, b in bnd for v in (a, b)], dtype=np.int64))
    if len(bv) > 200000: return faces, 0
    Pv = X[bv]; order = np.argsort(Pv[:, 0]); xs = Pv[order, 0]
    inserts = {}
    for fi, a, b in bnd:
        pa, pb = X[a], X[b]
        lo = np.searchsorted(xs, min(pa[0], pb[0]) - tol); hi = np.searchsorted(xs, max(pa[0], pb[0]) + tol, side="right")
        if hi <= lo: continue
        cand = bv[order[lo:hi]]; cand = cand[(cand != a) & (cand != b)]
        if len(cand) == 0: continue
        d = pb - pa; L2 = float(d @ d)
        if L2 <= 0: continue
        C = X[cand]; t = ((C - pa) @ d) / L2; Lq = math.sqrt(L2)
        ok = (t * Lq > tol) & ((1 - t) * Lq > tol)
        if not ok.any(): continue
        C2, t2, c2 = C[ok], t[ok], cand[ok]
        dist = np.linalg.norm(C2 - (pa + np.outer(t2, d)), axis=1); sel = dist <= tol
        if not sel.any(): continue
        inserts[(fi, a, b)] = [int(v) for _, v in sorted(zip(t2[sel].tolist(), c2[sel].tolist()))]
    if not inserts: return faces, 0
    n = 0; out = []
    for fi, f in enumerate(faces):
        nf = []
        for lp in f:
            nl = []
            for j in range(len(lp)):
                a, b = lp[j], lp[(j + 1) % len(lp)]
                nl.append(a); ins = inserts.get((fi, a, b))
                if ins: nl.extend(ins); n += len(ins)
            nf.append(nl)
        out.append(nf)
    return out, n


TOL_SEW = max(10.0 / QS, 0.02)  # ifc2step6 Repair.tol_sew at --prec 2: seam vertices merged (0.1 mm)


def _canon(o):
    k = min(range(len(o)), key=lambda i: o[i])
    return tuple(o[k:] + o[:k])


def _dedup(faces):
    """port of ifc2step6 Repair.dedup_faces: identical faces dropped; opposite-orientation pairs whose edges are all used twice
    by the other faces (contact wall of two touching solids) removed. -> (faces, twins kept [(i, j)])"""
    seen = set(); out = []
    for f in faces:
        key = (_canon(f[0]), len(f))
        if key in seen: continue
        seen.add(key); out.append(f)
    canon = {_canon(f[0]): i for i, f in enumerate(out) if len(f) == 1}
    pairs = []
    for cyc, i in canon.items():
        j = canon.get(_canon(list(cyc[::-1])))
        if j is not None and i < j: pairs.append((i, j))
    if not pairs: return out, []
    inpair = {i for p_ in pairs for i in p_}
    use = _edge_counts([f for i, f in enumerate(out) if i not in inpair])
    drop = set()
    for i, j in pairs:
        o = out[i][0]; m = len(o)
        if all(use.get((min(o[t], o[(t + 1) % m]), max(o[t], o[(t + 1) % m])), 0) >= 2 for t in range(m)):
            drop.add(i); drop.add(j)
    twins = [(i, j) for i, j in pairs if i not in drop]
    if drop:
        keep = [i for i in range(len(out)) if i not in drop]; ren = {o_: n_ for n_, o_ in enumerate(keep)}
        twins = [(ren[i], ren[j]) for i, j in twins]; out = [out[i] for i in keep]
    return out, twins


def _free(faces):
    return sum(1 for v in _edge_counts(faces).values() if v == 1)


def _sew(faces, X, tol=TOL_SEW):
    """port of ifc2step6 Repair.sew: merge boundary vertices closer than tol (moves a vertex by < tol, never adds a face);
    degenerate loops / zero-area faces dropped; kept only if the open edges decrease. -> (faces, merged)"""
    import numpy as np
    cnt = _edge_counts(faces)
    bnd = [k for k, v in cnt.items() if v == 1]
    if not bnd: return faces, 0
    bv = np.unique(np.array([v for k in bnd for v in k], dtype=np.int64))
    if len(bv) > 100000: return faces, 0
    P = X[bv]; order = np.argsort(P[:, 0]); xs = P[order, 0]; parent = {}
    def find(a):
        while parent.get(a, a) != a: a = parent[a]
        return a
    merged = 0
    for ii in range(len(order)):
        i = order[ii]; hi = np.searchsorted(xs, xs[ii] + tol, side="right")
        if hi <= ii + 1: continue
        cj = order[ii + 1:hi]; d = np.linalg.norm(P[cj] - P[i], axis=1)
        for j in cj[d <= tol].tolist():
            a, b = find(int(bv[i])), find(int(bv[j]))
            if a != b: parent[max(a, b)] = min(a, b); merged += 1
    if not merged: return faces, 0
    rep = {v: find(v) for v in list(parent.keys())}
    out = []
    for f in faces:
        nf = []
        for k, lp in enumerate(f):
            q = [rep.get(i, i) for i in lp]
            c = [v for j, v in enumerate(q) if v != q[j - 1]] if len(q) > 1 else q
            if len(c) < 3 or len(set(c)) < 3:
                if k == 0: nf = None; break
                continue
            nf.append(c)
        if nf:
            o = nf[0]; Q = X[o] - X[o[0]]; R = np.roll(Q, -1, axis=0)
            n = np.cross(Q, R).sum(0)                          # Newell normal: zero-area faces dropped
            if float(n @ n) > 1e-20: out.append(nf)
    if _free(out) >= len(bnd): return faces, 0
    return out, merged


def closure(face_pts, scale):
    """the 6.1.x repair chain on one shell (poly-loop faces, file units), adding no face:
    weld (0.01 mm) -> dedup -> one side of a double-sided mesh -> sew (0.1 mm) -> dedup -> T-junctions -> free edges.
    -> dict(free_weld, free_sew, free_after, sewn, inserted, double_sided, nonmanifold)"""
    faces, X = _weld(face_pts, scale)
    faces, tw = _dedup(faces)
    dbl = bool(tw) and 2 * len(tw) >= 0.5 * len(faces)
    if dbl:
        drop = {j for i, j in tw}; faces = [f for k, f in enumerate(faces) if k not in drop]
    fw = _free(faces)
    sewn = ins = 0; fs_ = fw
    if fw:
        f2, sewn = _sew(faces, X)
        if sewn: faces, _ = _dedup(f2)
        fs_ = _free(faces)
        if fs_:
            faces, ins = _tjunctions(faces, X)
    c1 = _edge_counts(faces)
    return dict(free_weld=fw, free_sew=fs_, free_after=sum(1 for v in c1.values() if v == 1), sewn=sewn, inserted=ins,
                double_sided=int(dbl), nonmanifold=sum(1 for v in c1.values() if v > 2))


def _loops(face):
    """IfcFace -> [loop [(x,y,z)]] or None when a bound is not an IfcPolyLoop"""
    out = []
    for bd in face.Bounds:
        if not bd.Bound.is_a("IfcPolyLoop"): return None
        out.append([tuple(q.Coordinates) for q in bd.Bound.Polygon])
    return out


def source_state_v2(e, scale):
    """v1 (verifier) state + the T-junction-resolved closure state"""
    st = source_state(e); v1 = st["code"]
    its = body_items(e)
    shells = []
    for it in its:
        if it.is_a() in FACETED_ITEMS:
            shells.append([it.Outer])
        elif it.is_a("IfcShellBasedSurfaceModel"):
            shells.append(list(it.SbsmBoundary))
        elif it.is_a("IfcFaceBasedSurfaceModel"):
            shells.append(list(it.FbsmFaces))
    res = dict(v1=v1, items=st.get("items"))
    if v1 not in ("faceted_open", "faceted_watertight", "surface_model") or not shells:
        res["v2"] = v1; return res
    agg = collections.Counter(); unknown = False
    for group in shells:
        for sh in group:
            fp = []
            for fc in sh.CfsFaces:
                lps = _loops(fc)
                if lps is None: unknown = True; break
                fp.append(lps)
            if unknown: break
            agg.update(closure(fp, scale))
        if unknown: break
    res.update({k: int(agg.get(k, 0)) for k in ("free_weld", "free_sew", "free_after", "sewn", "inserted", "double_sided", "nonmanifold")})
    if v1 == "surface_model":
        res["v2"] = "surface_model" if unknown else ("surface_model_open" if agg["free_after"] else "surface_model_closed")
    elif unknown:
        res["v2"] = v1
    elif agg["free_after"]:
        res["v2"] = "faceted_open"
    elif not agg["free_weld"]:
        res["v2"] = "faceted_watertight"
    elif not agg["free_sew"]:
        res["v2"] = "faceted_sew_closed"
    else:
        res["v2"] = "faceted_tjunction_closed"
    return res


def build(f, e, openings=True):
    """-> (n_faces, bbox[6] in metres) of the element built alone, or (0, None)"""
    import ifcopenshell.geom
    st = ifcopenshell.geom.settings()
    _set(st, "use-world-coords", "USE_WORLD_COORDS", True)
    if not openings: _set(st, "disable-opening-subtractions", "DISABLE_OPENING_SUBTRACTIONS", True)
    try:
        it = ifcopenshell.geom.iterator(st, f, 1, include=[e])
        if not it.initialize(): return 0, None
        sh = it.get(); v = sh.geometry.verts; nf = len(sh.geometry.faces) // 3
        if not v: return nf, None
        xs, ys, zs = v[0::3], v[1::3], v[2::3]
        return nf, [min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)]
    except Exception:
        return 0, None


def prepare(src, wd):
    """the source as the IFC worker converts it: zip -> largest .ifc member, gzip -> raw; an IFC2X2 / interim schema name declared
    as the schema IfcOpenShell loads (ifc/worker.py unpack + fix_schema) -> (path, notes)"""
    import zipfile, shutil, re
    notes = []; os.makedirs(wd, exist_ok=True)
    with open(src, "rb") as f: head = f.read(8)
    if head[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(src) as z:
            infos = [i for i in z.infolist() if not i.is_dir()]
            m = max([i for i in infos if i.filename.lower().endswith(".ifc")] or infos, key=lambda i: i.file_size)
            out = os.path.join(wd, "attrib_src.ifc")
            with z.open(m) as x, open(out, "wb") as y: shutil.copyfileobj(x, y, 1 << 24)
        src = out; notes.append(f"zip member {m.filename}")
    elif head[:2] == b"\x1f\x8b":
        out = os.path.join(wd, "attrib_src.ifc")
        with gzip.open(src) as x, open(out, "wb") as y: shutil.copyfileobj(x, y, 1 << 24)
        src = out; notes.append("gunzipped")
    with open(src, "rb") as f: hd = f.read(1 << 16)
    m = re.search(rb"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", hd)
    sc = m.group(1).decode("latin-1").upper() if m else None
    to = (b"IFC2X3" if sc in ("IFC2X2_FINAL", "IFC2X_FINAL", "IFC2X2", "IFC2X", "IFC2X2_PLATFORM", "IFC2X_PLATFORM", "IFC2X3_FINAL", "IFC2X3_TC1") else
          b"IFC4X3_ADD2" if sc in ("IFC4X1", "IFC4X2", "IFC4X3_RC1", "IFC4X3_RC2", "IFC4X3_RC3", "IFC4X3_RC4", "IFC4X3_TC1", "IFC4X3_ADD1") else None)
    if to:
        data = open(src, "rb").read(); m = re.search(rb"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", data[:1 << 16])
        out = os.path.join(wd, "attrib_src_schemafix.ifc"); open(out, "wb").write(data[:m.start(1)] + to + data[m.end(1):])
        src = out; notes.append(f"schema {sc} declared {to.decode()}")
    return src, notes


def covers(o, b, tol=COVER_TOL_M):
    return all(o[k] <= b[k] + tol for k in range(3)) and all(o[k + 3] >= b[k + 3] - tol for k in range(3))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("src"); ap.add_argument("src_parts"); ap.add_argument("step_parts"); ap.add_argument("out")
    ap.add_argument("--max-surface", type=int, default=20000); ap.add_argument("--max-missing", type=int, default=500)
    ap.add_argument("--closed-surface-models", choices=("source", "pipeline"), default="pipeline",
                    help="cause of surface-model parts whose shells all close after the repair chain (main 2026-10-02: pipeline - a closed "
                         "volume written as a surface is converter work left undone)")
    ap.add_argument("--unpack-dir", help="where to unpack a zip / gzip source and write a schema-fixed copy (default: next to OUT)")
    a = ap.parse_args(); t0 = time.time()
    src = load(a.src_parts); step = load(a.step_parts)
    gid_part = {p["gid"]: p for p in src if p.get("gid")}
    present = [s for s in step if (s.get("solids") or 0) > 0 or (s.get("faces") or 0) > 0]
    pids = {s.get("pid") for s in present}
    # join mode as grade_join: by GlobalId only when the STEP ids are source GlobalIds (older writers: names -> no per-part pairing)
    hit = sum(1 for g in gid_part if g in pids)
    if not (gid_part and hit >= 0.5 * min(len(gid_part), max(1, len(pids)))):
        out = dict(version=VERSION, join_mode="not_gid", skipped="STEP ids are not source GlobalIds (older writer): no per-part attribution",
                   surface=dict(n=None), missing=dict(n=None), sec=round(time.time() - t0, 1))
        json.dump(out, open(a.out, "w"), indent=1); print(json.dumps(out)); return
    a.src, notes = prepare(a.src, a.unpack_dir or os.path.dirname(os.path.abspath(a.out)))
    import ifcopenshell
    surf = sorted({s["pid"] for s in present if (s.get("solids") or 0) == 0 and s.get("pid") in gid_part})
    miss = sorted(g for g in gid_part if g not in pids)
    out = dict(version=VERSION, join_mode="gid", src=os.path.basename(a.src), input_notes=notes, surface=dict(n=len(surf)), missing=dict(n=len(miss)))
    f = ifcopenshell.open(a.src)
    # 1. surface parts
    stride = 1 if len(surf) <= a.max_surface else -(-len(surf) // a.max_surface)
    chk = surf[::stride]
    try:
        import ifcopenshell.util.unit
        scale = float(ifcopenshell.util.unit.calculate_unit_scale(f)) * 1000.0      # file length unit -> mm
    except Exception:
        scale = 1.0
    src_states = {"faceted_open", "surface_model", "surface_model_open"} | ({"surface_model_closed"} if a.closed_surface_models == "source" else set())
    by = collections.Counter(); by1 = collections.Counter(); cause = collections.Counter(); cause1 = collections.Counter()
    ex = collections.defaultdict(list); cat_src = collections.Counter(); moved = collections.Counter(); tj = collections.Counter(); pipe_parts = []
    for g in chk:
        try:
            e = f.by_guid(g); r2 = source_state_v2(e, scale); st, s1 = r2["v2"], r2["v1"]
        except Exception as x:
            r2 = {}; st = s1 = "unresolved"
        c = "source" if st in src_states else "pipeline"
        c1 = "source" if s1 in ("surface_model", "faceted_open") else "pipeline"
        by[st] += 1; by1[s1] += 1; cause[c] += 1; cause1[c1] += 1
        if c1 != c: moved[f"{c1}->{c}"] += 1
        for k_ in ("free_weld", "free_sew", "free_after", "sewn", "inserted", "double_sided"): tj[k_] += r2.get(k_, 0) or 0
        if c == "source": cat_src[gid_part[g].get("cat")] += 1
        elif len(pipe_parts) < 500: pipe_parts.append([g, gid_part[g].get("cls"), gid_part[g].get("name"), st])
        if len(ex[st]) < 10: ex[st].append([g, gid_part[g].get("cls"), gid_part[g].get("name")])
    k = len(surf) / max(1, len(chk))
    out["surface"].update(checked=len(chk), sampled=stride > 1, by_state=dict(by), source=int(round(cause["source"] * k)), pipeline=int(round(cause["pipeline"] * k)),
                          source_by_category=dict(cat_src), examples=dict(ex), closed_surface_models=a.closed_surface_models, unit_scale_mm=scale,
                          v1=dict(by_state=dict(by1), source=int(round(cause1["source"] * k)), pipeline=int(round(cause1["pipeline"] * k))),
                          moved_vs_v1=dict(moved), repair=dict(tj), pipeline_parts=pipe_parts)
    # 2. missing parts
    mc = collections.Counter(); voided = []; mex = collections.defaultdict(list)
    for g in miss[:a.max_missing]:
        p = gid_part[g]
        try: e = f.by_guid(g)
        except Exception: mc["unresolved"] += 1; continue
        if not body_items(e):
            c = "no_body"
        else:
            n1, _ = build(f, e, True)
            if n1 > 0: c = "buildable"
            else:
                n0, bb = build(f, e, False)
                if n0 == 0 or bb is None: c = "not_buildable"
                else:
                    hit = None
                    for r in (getattr(e, "HasOpenings", None) or []):
                        o = r.RelatedOpeningElement
                        _, ob = build(f, o, True)
                        if ob is not None and covers(ob, bb):
                            hit = dict(opening=o.GlobalId, opening_bbox_m=[round(x, 4) for x in ob], element_bbox_m=[round(x, 4) for x in bb]); break
                    c = "voided" if hit else "cut_empty"
                    if hit: voided.append(dict(gid=g, cls=p.get("cls"), cat=p.get("cat"), name=p.get("name"), **hit))
        mc[c] += 1
        if len(mex[c]) < 10: mex[c].append([g, p.get("cls"), p.get("name")])
    out["missing"].update(checked=min(len(miss), a.max_missing), by_cause=dict(mc), voided=voided,
                          voided_by_category=dict(collections.Counter(v["cat"] for v in voided)), examples=dict(mex))
    out["sec"] = round(time.time() - t0, 1)
    json.dump(out, open(a.out, "w"), indent=1, default=str)
    print(json.dumps({"surface": {k: out["surface"].get(k) for k in ("n", "source", "pipeline", "by_state", "moved_vs_v1")},
                      "missing": {k: out["missing"].get(k) for k in ("n", "by_cause")}, "sec": out["sec"]}))


if __name__ == "__main__":
    main()
