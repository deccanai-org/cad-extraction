"""Rules: every finding gets a code, a level and a cause. FAIL if any FAIL finding, WARN if any WARN, else PASS.
Causes: PIPELINE (conversion or publishing is wrong), DECODER (the .db1 reading is wrong or incomplete), SOURCE (the
input itself), EVIDENCE (what could be checked), BY_DESIGN (the converter skips it on purpose)."""
from . import config as C

LEVEL = {"F": "FAIL", "W": "WARN", "I": "INFO"}


def _add(res, code, cause, msg, **kw):
    res.setdefault("findings", []).append(dict(code=code, level=LEVEL[code[0]], cause=cause, message=msg, **kw))


def decide(res):
    rec = res.get("record") or {}; st = res.get("step") or {}; inp = res.get("input") or {}
    geo = res.get("geometry") or {}; rep = res.get("reproduce") or {}; tr = res.get("truth") or {}; vl = res.get("vlm") or {}
    res["findings"] = []
    # ---- record + publication
    if rec.get("error") or rec.get("status") != "ok":
        _add(res, "F_NO_RECORD", "PIPELINE", f"no ok conversion record ({rec.get('status') or rec.get('error')})")
    if (res.get("step_object") or {}).get("error"):
        _add(res, "F_STEP_MISSING", "PIPELINE", "STEP object not in the bucket")
    elif rec.get("out_bytes") is not None and res["step_object"].get("bytes") != rec.get("out_bytes"):
        _add(res, "W_RECORD_STALE", "PIPELINE", f"published STEP is {res['step_object'].get('bytes')} B, the record says {rec.get('out_bytes')} B: "
             "the record does not describe the published file (re-uploaded without a new record)")
    if rec.get("code") and rec["code"] != C.CURRENT_CODE:
        _add(res, "I_OLDER_CODE", "EVIDENCE", f"converted by {rec['code']} (kept by the production run), current is {C.CURRENT_CODE}")
    if rec.get("excluded_elements"):
        _add(res, "W_RESCUE_EXCLUDED", "PIPELINE", f"{len(rec['excluded_elements']) if isinstance(rec['excluded_elements'], list) else rec['excluded_elements']} "
             "element(s) left out after the geometry kernel crashed on them")
    # ---- input
    if inp.get("in_bucket") is False:
        if (inp.get("source_bucket") or {}).get("found"):
            _add(res, "W_INPUT_ONLY_IN_ARCHIVE", "SOURCE", f"input .db1 gone from {C.BUCKET}; located in {C.SRC_BUCKET}: {inp['source_bucket']['bim_key']}")
        else:
            _add(res, "F_INPUT_MISSING", "SOURCE", "input .db1 not found in either bucket")
    if inp.get("sha256") and inp["sha256"] != res["sha"]:
        _add(res, "F_INPUT_SHA", "PIPELINE", "sha256 of the input .db1 does not equal the STEP's name: STEP belongs to another input")
    if inp.get("engine") and rec.get("engine") and inp["engine"] != rec["engine"]:
        _add(res, "W_ENGINE_MISMATCH", "PIPELINE", f"input banner says Xsteel {inp['engine']}, the record {rec['engine']}")
    if (inp.get("source_bucket") or {}).get("found"):
        _add(res, "I_SOURCE_ARCHIVE", "EVIDENCE", f"original archive: s3://{C.SRC_BUCKET}/{inp['source_bucket']['bim_key']}")
    # ---- STEP file
    if st:
        if st.get("kind") != "step":
            _add(res, "F_NOT_STEP", "PIPELINE", f"file kind: {st.get('kind')}")
        else:
            if not st.get("end_marker"): _add(res, "F_TRUNCATED", "PIPELINE", "END-ISO-10303-21 missing")
            if C.REQUIRED_SCHEMA not in (st.get("schema") or "").upper(): _add(res, "F_SCHEMA", "PIPELINE", f"schema {st.get('schema')}, expected {C.REQUIRED_SCHEMA}")
            bad = {k: v for k, v in (st.get("entities") or {}).items() if k in C.FORBIDDEN_ENTITIES}
            if bad: _add(res, "F_FLAVOUR", "PIPELINE", f"non-faceted entities present: {bad}")
            if st.get("length_unit") != "mm": _add(res, "W_UNIT", "PIPELINE", f"length unit {st.get('length_unit')}, expected mm")
            nb = (st.get("entities") or {}).get("FACETED_BREP", 0); npd = st.get("products", 0)
            w = (rec.get("convert") or {}).get("written")
            if npd != nb: _add(res, "W_PRODUCT_SOLID_COUNT", "PIPELINE", f"{npd} products but {nb} faceted solids")
            if w is not None and npd != w:
                lvl = "W_PARTS_DROPPED" if npd < w else "W_PARTS_EXTRA"
                _add(res, lvl, "PIPELINE", f"decoder wrote {w} parts to the IFC, the STEP holds {npd} ({npd - w:+d})")
    # ---- decoder coverage (from the record: what the decoder could not build)
    cv = rec.get("convert") or {}
    sk = cv.get("skipped") or {}
    lost = sum(sk.get(k, 0) for k in ("unresolved", "contour_plate_no_outline", "implausible_profile", "writer_skip"))
    cand = (cv.get("written") or 0) + lost
    if cand:
        res["decoder_loss_share"] = lost / cand
        if lost / cand > 0.2:
            _add(res, "W_DECODER_LOSS", "DECODER", f"{lost} of {cand} buildable members not written (unresolved profile / no outline / implausible)",
                 top=cv.get("unresolved_top", [])[:8])
        elif lost:
            _add(res, "I_DECODER_LOSS", "DECODER", f"{lost} of {cand} buildable members not written", top=cv.get("unresolved_top", [])[:5])
    mb, mem = cv.get("mb"), cv.get("members")
    if mb and mb >= C.SPARSE_MIN_MB and mem is not None and mem / mb < C.SPARSE_MEMBERS_PER_MB:
        if tr.get("status") == "matched" and (tr.get("recall_with_near") or 0) >= 0.8:
            # a bloated .db1 (history, numbering) of a genuinely small model: the Tekla export confirms it is complete
            _add(res, "I_SPARSE_CONFIRMED", "EVIDENCE", f"{mem} members in a {mb:.0f} MB model, but the Tekla export confirms the model is complete")
        else:
            _add(res, "W_SPARSE_DECODE", "DECODER", f"only {mem} members decoded from a {mb:.0f} MB model ({mem / mb:.1f}/MB; the fleet median is "
                 f"~230/MB): most of the model was probably not found (or the file is bloated)")
    if sk.get("bolt_group_excluded"): _add(res, "I_BOLTS_EXCLUDED", "BY_DESIGN", f"{sk['bolt_group_excluded']} bolt groups not converted (by design)")
    yv = cv.get("y_vertical_frac_I"); nh = cv.get("horizontal_I") or 0
    if yv is not None and nh >= 20 and yv < 0.8:
        _add(res, "W_ORIENTATION", "DECODER", f"only {yv:.0%} of {nh} horizontal I-sections stand web-vertical")
    # ---- geometry
    if geo.get("error"): _add(res, "F_UNREADABLE", "PIPELINE", geo["error"])
    elif geo.get("skipped"): _add(res, "I_GEOMETRY_SKIPPED", "EVIDENCE", geo["skipped"])
    elif geo:
        k = geo.get("kinds", {}); n = max(1, geo.get("parts", 0))
        if not k.get("solid"): _add(res, "F_NO_SOLIDS", "PIPELINE", "OpenCascade finds no valid solid")
        badk = {x: k[x] for x in ("impossible_solid", "inverted_solid", "degenerate_solid", "no_solid", "empty") if k.get(x)}
        if badk:
            _add(res, "W_BAD_SOLIDS" if sum(badk.values()) / n > 0.01 else "I_BAD_SOLIDS", "PIPELINE", f"{badk} of {n} parts")
        if geo.get("roots") is not None and st.get("products") and geo["roots"] != st["products"]:
            _add(res, "W_ROOTS", "PIPELINE", f"OpenCascade transfers {geo['roots']} roots, file has {st['products']} products")
        if max(geo.get("core_extent_mm") or [0]) > C.MAX_MODEL_EXTENT_MM:
            _add(res, "F_EXTENT", "DECODER", f"model core is {max(geo['core_extent_mm']) / 1e6:.1f} km across")
        ext, core = max(geo.get("extent_mm") or [0]), max(geo.get("core_extent_mm") or [0])
        if geo.get("stray_parts") and ext > C.FAR_STRAY_MM and ext > C.FAR_STRAY_FACTOR * max(core, 1.0):
            _add(res, "W_FAR_STRAY", "DECODER", f"{geo['stray_parts']} stray part(s) stretch the model to {ext / 1e6:.1f} km (the model itself is "
                 f"{core / 1e3:.0f} m): a corrupted position", examples=geo.get("stray_examples"))
        elif geo.get("stray_share", 0) > C.OUTLIER_SHARE_WARN:
            _add(res, "W_STRAY_PARTS", "DECODER", f"{geo['stray_parts']} parts far outside the model", examples=geo.get("stray_examples"))
        elif geo.get("stray_parts"):
            _add(res, "I_STRAY_PARTS", "DECODER", f"{geo['stray_parts']} parts far outside the model", examples=geo.get("stray_examples"))
        if geo.get("duplicate_share", 0) > C.DUP_SHARE_WARN:
            _add(res, "W_DUPLICATES", "DECODER", f"{geo['coincident_duplicates']} parts coincide exactly with another part")
        chk = geo.get("brepcheck_checked") or 0
        if chk and geo.get("brepcheck_invalid", 0) / chk > C.BREPCHECK_WARN_SHARE:
            _add(res, "W_BREPCHECK", "PIPELINE", f"{geo['brepcheck_invalid']} of {chk} checked solids fail BRepCheck")
    # ---- reproduction
    if rep.get("skipped"): _add(res, "I_REPRO_SKIPPED", "EVIDENCE", rep["skipped"])
    elif rep.get("status") and rep.get("status") != "ok":
        _add(res, "W_REPRO_FAILED", "EVIDENCE", f"re-running the decoder gave status {rep.get('status')}")
    elif rep.get("match"):
        m = rep["match"]; share = m.get("precision_a", 0)
        if share < 0.9: _add(res, "F_REPRO_MISMATCH", "PIPELINE", f"only {share:.1%} of STEP parts are reproduced from the input .db1")
        elif share < C.REPRO_MATCH_MIN:
            if rep.get("same_counts_as_record") and m.get("a") == m.get("b"):
                # same parts, same names, same count: the leftovers are round bars / cut members whose tessellated volume
                # differs by > 3 % between the verifier's mesher and the production STEP writer
                _add(res, "I_REPRO_TESSELLATION", "EVIDENCE", f"{share:.1%} of STEP parts reproduced exactly; the part count is identical and the rest "
                     f"differ only in tessellated volume (e.g. {', '.join(sorted({x.get('name') or '?' for x in rep.get('unreproduced_examples', [])[:5]}))})")
            else:
                _add(res, "W_REPRO_PARTIAL", "PIPELINE", f"{share:.1%} of STEP parts reproduced from the input .db1")
    # ---- ground truth
    if tr.get("status") == "none": _add(res, "I_NO_TRUTH", "EVIDENCE", "no Tekla IFC export next to the .db1")
    elif tr.get("status") == "timeout":
        _add(res, "W_TRUTH_TIMEOUT", "EVIDENCE", f"the Tekla export could not be meshed in {C.TRUTH_MESH_TIMEOUT_S} s (IfcOpenShell boolean loop): no ground-truth comparison")
    elif tr.get("status") == "unaligned":
        no = tr.get("name_overlap")
        if no is not None and no >= 0.7:
            _add(res, "F_TRUTH_GEOMETRY", "DECODER", f"the Tekla export has the same profiles ({no:.0%} overlap) but no placement agrees")
        else:
            _add(res, "I_TRUTH_OTHER_MODEL", "EVIDENCE", f"the export next to the .db1 is not this model (profile overlap {no if no is None else round(no, 2)})")
    elif tr.get("status") == "matched":
        m = tr["match"]; rc = m["recall_b"]; pi = m["precision_a_inside"]
        if rc >= C.TRUTH_RECALL_PASS:
            _add(res, "I_TRUTH_CONFIRMED", "EVIDENCE", f"{rc:.1%} of the {m['b']} Tekla export elements are in the STEP (median {m['median_dist_mm']:.2f} mm)")
        elif rc >= C.TRUTH_RECALL_WARN:
            _add(res, "W_TRUTH_PARTIAL", "DECODER", f"{rc:.1%} of the {m['b']} Tekla export elements are in the STEP (median {m['median_dist_mm']:.2f} mm); "
                 f"{m['near']} more sit within {C.TRUTH_NEAR_DIST_MM:.0f} mm with a different volume, {m['b'] - m['matched'] - m['near']} have no STEP part nearby",
                 near=tr.get("near_examples", [])[:6], missing=tr.get("missing_examples", [])[:6])
        else:
            no = tr.get("name_overlap") or 0
            _add(res, "F_TRUTH_MISMATCH" if no >= C.NAME_OVERLAP_MIN else "W_TRUTH_WEAK", "DECODER",
                 f"only {rc:.1%} of the {m['b']} Tekla export elements are in the STEP (profile overlap {no:.0%}; "
                 f"{m['near']} in place with another volume)")
        iv = tr.get("in_place_other_volume") or {}
        if iv.get("n", 0) >= max(5, 0.03 * m["b"]):
            _add(res, "W_VOLUME_DIFF", "DECODER", f"{iv['n']} export elements are exactly in place but the STEP part's volume differs "
                 f"(median x{iv['median_vol_ratio']:.2f}, STEP larger in {iv['step_larger']}): copes / fittings / cuts not applied")
        dp = tr.get("displacement") or {}
        if dp.get("displaced", 0) >= max(5, 0.03 * m["b"]):
            _add(res, "W_DISPLACED_PARTS", "DECODER", f"{dp['displaced']} export elements have a same-profile STEP part {dp['median_offset_mm']:.0f} mm "
                 f"away (median; per axis {[round(x) for x in dp['median_axis_offset_mm']]} mm): placed with an offset, not missing",
                 by_profile=dp.get("by_profile"))
        if dp.get("absent", 0) >= max(5, 0.03 * m["b"]):
            _add(res, "W_ABSENT_PARTS", "DECODER", f"{dp['absent']} export elements have no same-profile STEP part within 1 m: not converted")
    # ---- VLM
    if vl.get("overall") == "fail":
        _add(res, "F_VLM" if vl.get("confidence") == "high" else "W_VLM", "DECODER", f"visual check: {vl.get('notes')}", issues=vl.get("issues"))
    elif vl.get("overall") == "warn":
        _add(res, "W_VLM", "DECODER", f"visual check: {vl.get('notes')}", issues=vl.get("issues"))
    elif vl.get("overall") == "pass":
        _add(res, "I_VLM_PASS", "EVIDENCE", f"visual check: {vl.get('notes')}")
    elif vl.get("queued"):
        _add(res, "I_VLM_PENDING", "EVIDENCE", "visual check queued, not yet answered")
    for stg, err in sorted((res.get("stage_errors") or {}).items()):
        _add(res, "W_STAGE_ERROR", "EVIDENCE", f"stage {stg} could not run: {err}")    # never a silent pass
    lv = [f["level"] for f in res["findings"]]
    res["verdict"] = "FAIL" if "FAIL" in lv else "WARN" if "WARN" in lv else "PASS"
    res["pipeline_issue"] = any(f["cause"] == "PIPELINE" and f["level"] != "INFO" for f in res["findings"])
    res["decoder_issue"] = any(f["cause"] == "DECODER" and f["level"] != "INFO" for f in res["findings"])
    res["evidence"] = ("tekla_export" if tr.get("status") == "matched" and tr["match"]["recall_b"] >= C.TRUTH_RECALL_WARN else
                       "reproduced" if (rep.get("match") or {}).get("precision_a", 0) >= C.REPRO_MATCH_MIN else
                       "geometry" if geo and not geo.get("skipped") and not geo.get("error") else "integrity")
    res["codes"] = sorted({f["code"] for f in res["findings"]})
    return res
