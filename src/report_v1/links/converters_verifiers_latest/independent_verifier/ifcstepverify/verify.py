"""Verify one STEP file against its candidate source IFC(s). Pure function of the inputs + rules + library versions."""
import os, sys, json, time, hashlib, platform
from . import VERSION, config as C
from .stepfile import scan
from . import ifcsource, verdict


def _versions():
    import importlib.metadata as md
    v = {"ifcstepverify": VERSION, "rules": C.RULES_VERSION, "python": platform.python_version()}
    for d in ("cadquery-ocp", "ifcopenshell", "numpy"):
        try: v[d] = md.version(d)
        except Exception: v[d] = "unknown"
    return v


def _round(o):
    if isinstance(o, float): return float(f"{o:.{C.FLOAT_DIGITS}g}")
    if isinstance(o, dict): return {k: _round(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [_round(v) for v in o]
    return o


def verify(step_path, ifc_paths, ifc_base=None, manifest=None, step_relpath=None,
           step_geom_max=C.STEP_GEOM_MAX_BYTES, ifc_geom_max=C.IFC_GEOM_MAX_BYTES, threads=None, cand_workers=None):
    """manifest: {relpath: {sha256, bytes}} of the package, or None. Returns (result, run_info)."""
    t0 = time.time(); run = {}
    s = scan(step_path); t_scan = time.time()
    res = {"step": {k: v for k, v in s.items() if k not in ("product_names", "uuids")},
           "step_elements": len(s["uuids"]) if s["uuids"] else len(s["product_names"]),
           "match_method": "IFC GlobalId (IfcConvert product uuid)" if s["uuids"] else "PRODUCT name = IFC element name (ifc2step)"}
    if manifest is not None:
        m = manifest.get(step_relpath)
        res["manifest"] = {"found": m is not None, "sha256": m and m.get("sha256"), "bytes": m and m.get("bytes"), "relpath": step_relpath}
    if s["kind"] == "step" and s["is_ifc_conversion"] and s["end_marker"] and s["schema_class"] == "geometry":
        man_sha = {k: v.get("sha256") for k, v in (manifest or {}).items()}
        cands = ifcsource.discover(ifc_paths, base=ifc_base, manifest_sha=man_sha)
        ifcsource.score_all(cands, s, cand_workers)
        best, combo = ifcsource.choose(cands, s)
        res["source"] = {"candidates": [{k: c.get(k) for k in ("rel", "bytes", "sha256", "copies", "schema", "physical_elements", "match_key",
                                                                 "overlap", "precision", "missing_in_step", "extra_in_step", "error", "not_scored")} for c in cands],
                         "best": None if not best else {k: best.get(k) for k in ("rel", "bytes", "sha256", "schema", "physical_elements", "match_key",
                                                                                   "overlap", "precision", "missing_in_step", "extra_in_step")},
                         "combination": combo}
        t_src = time.time(); run["t_source_s"] = round(t_src - t_scan, 1)
        if best:
            import ifcopenshell
            from .geometry import analyze_step, analyze_ifc
            from .attribution import attribute
            f = ifcopenshell.open(best["path"])
            geo, mesh, msum = None, None, None
            if s["bytes"] <= step_geom_max:
                geo = analyze_step(step_path)
            else:
                geo = {"skipped": f"STEP is {s['bytes'] / 1e6:.0f} MB, above the {step_geom_max / 1e6:.0f} MB geometry limit: integrity + element matching only"}
            if best["bytes"] <= ifc_geom_max:
                mesh, msum = analyze_ifc(f, threads)
                res["ifc_mesh_summary"] = msum
            run["t_geometry_s"] = round(time.time() - t_src, 1)
            res["attribution"] = attribute(f, s, geo if geo and "parts" in geo else None, mesh, best["path"])
            res["geometry"] = {k: v for k, v in (geo or {}).items() if k != "parts"}
    verdict.decide(res)
    res = _round(res)
    res["versions"] = _versions()
    blob = json.dumps({k: v for k, v in res.items() if k != "versions"}, sort_keys=True, ensure_ascii=False).encode("utf-8")
    res["result_digest"] = hashlib.sha256(blob).hexdigest()
    run.update(t_total_s=round(time.time() - t0, 1), t_scan_s=round(t_scan - t0, 1), host=platform.node())
    return res, run


def write(res, run, out_dir, stem):
    """<stem>.json (result + run), <stem>_elements.csv (every flagged part / missing element)."""
    import csv
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, stem + ".json"), "w", encoding="utf-8") as f:
        json.dump({"result": res, "run": run}, f, indent=1, sort_keys=True, ensure_ascii=False)
    a = res.get("attribution", {})
    cols = ["kind", "issue", "cause_class", "cause", "step_part", "step_name", "ifc_type", "ifc_name", "ifc_globalid", "match",
            "source_state", "source_holed_faces", "where_mm", "step_volume_m3", "own_box_m3", "ifc_volume_m3", "confidence"]
    with open(os.path.join(out_dir, stem + "_elements.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, cols, extrasaction="ignore"); w.writeheader()
        for r in a.get("parts", []): w.writerow({"kind": "step_part", **r})
        for r in a.get("missing", []): w.writerow({"kind": "missing_ifc_element", "issue": "missing", **r})
