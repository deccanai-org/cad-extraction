"""Verdict rules. Each reason: code (stable id), level FAIL/WARN/INFO, cause class, message.
Fail-closed: anything the attribution cannot explain is UNCLASSIFIED and counts as WARN."""
import collections
from . import config as C


def R(code, level, cause, msg, n=None):
    return dict(code=code, level=level, cause_class=cause, count=n, message=msg)


def decide(res):
    s = res["step"]; out = []
    # ---- file level
    if s["kind"] == "empty": out.append(R("F_EMPTY", "FAIL", "PIPELINE", "file is empty (0 bytes)"))
    elif s["kind"] == "compressed": out.append(R("F_COMPRESSED", "FAIL", "PACKAGING", "file is compressed (gzip/zip), not a plain STEP"))
    elif s["kind"] == "not_step": out.append(R("F_NOT_STEP", "FAIL", "PACKAGING", "not an ISO-10303-21 file (e.g. a settings file with a .step name)"))
    else:
        if not s["end_marker"]: out.append(R("F_TRUNCATED", "FAIL", "PIPELINE", "END-ISO-10303-21 missing: file is cut off"))
        if s["schema_class"] == "cis2": out.append(R("F_NOT_GEOMETRY", "FAIL", "SOURCE", f"CIS/2 structural data, no geometry ({s['schema']})"))
        elif s["schema_class"] != "geometry": out.append(R("F_SCHEMA", "FAIL", "PIPELINE", f"no geometry schema ({s['schema']})"))
        if s["solid_entities"] == 0 and s["surface_entities"] == 0: out.append(R("F_NO_GEOMETRY", "FAIL", "PIPELINE", "no solid or surface entities"))
    m = res.get("manifest")
    if m is not None:
        if not m.get("found"): out.append(R("W_NOT_IN_MANIFEST", "WARN", "PACKAGING", "STEP not listed in the package manifest"))
        elif m.get("sha256") != s["sha256"]: out.append(R("F_SHA_MISMATCH", "FAIL", "PACKAGING", "SHA-256 differs from the package manifest"))
        elif m.get("bytes") not in (None, s["bytes"]): out.append(R("F_SIZE_MISMATCH", "FAIL", "PACKAGING", "size differs from the package manifest"))
    if s["kind"] == "step" and not s["is_ifc_conversion"]:
        out.append(R("I_NOT_IFC_CONVERSION", "INFO", "SCOPE", f"writer '{s['writer']}' is not an IFC converter; IFC comparison is not applicable"))
    if any(r["level"] == "FAIL" for r in out) or (s["kind"] == "step" and not s["is_ifc_conversion"]):
        return finish(res, out)
    # ---- source match
    src = res.get("source")
    if not src or not src.get("best"):
        out.append(R("W_NO_SOURCE", "WARN", "FILES", "no candidate IFC could be matched (source file missing from the package?)"))
        return finish(res, out)
    b = src["best"]; ne = res["step_elements"]
    if b.get("precision", b["overlap"]) < C.NAME_MATCH_MIN:
        combo = src.get("combination")
        msg = f"only {b.get('precision', b['overlap']):.1%} of the STEP parts are found in the best IFC" + (f"; {len(combo['sources'])} IFCs together cover {combo['coverage']:.1%}" if combo else "")
        out.append(R("W_WEAK_SOURCE", "WARN", "FILES", msg))
    a = res.get("attribution", {})
    miss = collections.Counter(r["cause_class"] for r in a.get("missing", []))
    if miss["PIPELINE"]: out.append(R("W_MISSING_PIPELINE", "WARN", "PIPELINE", "IFC elements with buildable geometry are not in the STEP", miss["PIPELINE"]))
    if miss["SOURCE"]: out.append(R("I_MISSING_SOURCE", "INFO", "SOURCE", "IFC elements without usable geometry are not in the STEP", miss["SOURCE"]))
    if miss["BY_DESIGN"]: out.append(R("I_MISSING_BY_DESIGN", "INFO", "BY_DESIGN", "skipped element types (openings, spaces, grids, annotations)", miss["BY_DESIGN"]))
    if a.get("extra_step_parts"): out.append(R("W_EXTRA_PARTS", "WARN", "UNCLASSIFIED", "STEP parts with no counterpart in the chosen IFC", a["extra_step_parts"]))
    # ---- geometry
    g = res.get("geometry") or {}
    if g.get("skipped"): out.append(R("I_GEOMETRY_SKIPPED", "INFO", "SCOPE", g["skipped"]))
    if g.get("error"): out.append(R("W_GEOMETRY_ERROR", "WARN", "UNCLASSIFIED", g["error"]))
    gs = g.get("summary")
    if gs:
        pc = collections.Counter((r["issue"], r["cause_class"]) for r in a.get("parts", []))
        if gs["solid"] == 0 and gs["impossible_solid"] == 0 and gs["open_shell"]:
            cls = "SOURCE" if pc[("open_shell", "PIPELINE")] == 0 and pc[("open_shell", "UNCLASSIFIED")] == 0 else "PIPELINE"
            out.append(R("W_SURFACES_ONLY", "WARN", cls, "no closed solids at all: every part is an open shell", gs["open_shell"]))
        for issue, code, text in (("open_shell", "OPEN_SHELL", "parts are open shells, not closed solids"),
                                  ("broken_solid", "BROKEN_SOLID", "solids with volume larger than their own bounding box"),
                                  ("empty_part", "EMPTY_PART", "parts without geometry")):
            for cc in ("PIPELINE", "UNCLASSIFIED", "SOURCE"):
                n = pc[(issue, cc)]
                if n: out.append(R("W_" + code + "_" + cc, "WARN", cc, text, n))
        inv = gs["brepcheck_invalid"]
        if inv:
            lvl = "WARN" if inv > C.BREPCHECK_WARN_SHARE * max(1, gs["brepcheck_checked"]) else "INFO"
            out.append(R(("W_" if lvl == "WARN" else "I_") + "BREPCHECK", lvl, "PIPELINE", f"solids fail BRepCheck ({inv} of {gs['brepcheck_checked']} checked)", inv))
        im = res.get("ifc_mesh_summary")
        if im and im["elements_meshed"]:
            ratio = [round(x / (y * 1000), 6) if y else None for x, y in zip(sorted(gs["bbox_dims_mm"]), sorted(im["bbox_dims_m"]))]
            res["bbox_ratio"] = ratio
            if any(r is not None and abs(r - 1) > C.BBOX_RATIO_TOL for r in ratio): out.append(R("W_SIZE", "WARN", "PIPELINE", f"overall size differs from the IFC {ratio}"))
            if gs["solid"] and im["volume_m3_clean"] and not gs["open_shell"]:
                vr = round(gs["volume_m3_clean"] / im["volume_m3_clean"], 6); res["volume_ratio"] = vr
                if abs(vr - 1) > C.VOLUME_RATIO_TOL: out.append(R("W_VOLUME", "WARN", "UNCLASSIFIED", f"total solid volume {vr}x the IFC's (sound elements only)"))
            if im["impossible_elements"]: out.append(R("I_SOURCE_BROKEN", "INFO", "SOURCE", "IFC elements whose mesh volume exceeds their box", im["impossible_elements"]))
    return finish(res, out)


def finish(res, reasons):
    order = {"FAIL": 0, "WARN": 1, "INFO": 2}
    reasons.sort(key=lambda r: (order[r["level"]], r["code"]))
    res["reasons"] = reasons
    s = res["step"]
    if s["kind"] == "step" and not s["is_ifc_conversion"] and not any(r["level"] == "FAIL" for r in reasons):
        res["verdict"] = "OUT_OF_SCOPE"
    else:
        res["verdict"] = "FAIL" if any(r["level"] == "FAIL" for r in reasons) else "WARN" if any(r["level"] == "WARN" for r in reasons) else "PASS"
    res["pipeline_issue"] = any(r["level"] in ("FAIL", "WARN") and r["cause_class"] in ("PIPELINE", "PACKAGING") for r in reasons)
    res["cause_classes"] = sorted({r["cause_class"] for r in reasons if r["level"] in ("FAIL", "WARN")})
    return res
