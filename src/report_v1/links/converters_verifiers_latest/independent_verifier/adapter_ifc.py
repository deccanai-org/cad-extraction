#!/usr/bin/env python3
"""Zenitude-data-3 IFC -> STEP verification job: the teammate's ifc-step-verifier (ifcstepverify, shipped unchanged)
run on one data-3 model.

  PY adapter_ifc.py --step <local STEP> --source <local source IFC / .ifczip / .gz> --out <result.json> --id <sha256>
                    --workdir <dir> [--threads 2] [--step-geom-max 2e9] [--ifc-geom-max 1e9]

What the adapter does (and only this):
  * unpacks the source exactly as the IFC worker downloads it (zip: largest .ifc member; gzip), checks sha256 == --id;
  * our ifc2step5/6 STEPs write PRODUCT('<IFC GlobalId>','<Name>','<IFC class>'); ifcstepverify reads the FIRST string
    as the element name (it was built for a writer that put the Name there) and has an exact GlobalId mode for
    'product-<uuid>' ids (IfcConvert). The adapter passes our GlobalIds through that exact mode (uuids in file order,
    names = the second string), so matching is one-to-one by GlobalId. No rule, threshold or attribution is changed;
  * maps verdict / codes / causes into the fleet's verify-result schema, keeping every original code.
Exit code 0 whenever a result JSON was written (also for FAIL / CANNOT_VERIFY / ERROR verdicts)."""
import os, sys, json, time, argparse, shutil, zipfile, gzip, uuid, collections, traceback
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import z3v_common as Z

CAUSE = {"PIPELINE": "pipeline", "SOURCE": "source", "FILES": "files", "PACKAGING": "packaging", "BY_DESIGN": "by_design",
         "UNCLASSIFIED": "unclassified", "SCOPE": "unclassified"}
CSV_COLS = ["kind", "issue", "cause_class", "cause", "step_part", "step_name", "ifc_type", "ifc_name", "ifc_globalid", "match",
            "source_state", "source_holed_faces", "where_mm", "step_volume_m3", "own_box_m3", "ifc_volume_m3", "confidence"]


def unpack(src, wd):
    """-> (path of the IFC to verify, note). Mirrors ifc/worker.py unpack(): zip -> largest .ifc/.ifcxml member, gzip -> raw."""
    with open(src, "rb") as f: head = f.read(8)
    if head[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(src) as z:
            infos = [i for i in z.infolist() if not i.is_dir()]
            ifcs = [i for i in infos if i.filename.lower().endswith((".ifc", ".ifcxml"))] or infos
            m = max(ifcs, key=lambda i: i.file_size)
            out = os.path.join(wd, "src_unz" + (".ifcXML" if m.filename.lower().endswith(".ifcxml") else ".ifc"))
            with z.open(m) as a, open(out, "wb") as b: shutil.copyfileobj(a, b, 1 << 24)
            return out, f"zip member {m.filename}"
    if head[:2] == b"\x1f\x8b":
        out = os.path.join(wd, "src_gunz.ifc")
        with gzip.open(src) as a, open(out, "wb") as b: shutil.copyfileobj(a, b, 1 << 24)
        return out, "gunzipped"
    if src.lower().endswith(".ifc"): return src, None
    out = os.path.join(wd, "src.ifc")                       # the verifier discovers candidates by the .ifc suffix
    if os.path.lexists(out): os.remove(out)
    try: os.link(src, out)
    except OSError: shutil.copyfile(src, out)
    return out, "renamed to .ifc"


def install_scan_adapter(force_names=False):
    """GlobalId pass-through for our PRODUCT convention (see module doc); force_names: the verifier's native ifc2step
    name mode, fed the 2nd PRODUCT string (the element Name) - used when GlobalId mode cannot run."""
    import ifcopenshell.guid
    from ifcstepverify import stepfile, verify as V
    orig = stepfile.scan
    info = {}

    def scan(path):
        R = orig(path)
        if R.get("kind") != "step" or not R.get("is_ifc_conversion") or R.get("uuids"):
            return R
        T = Z.product_triples(path, stepfile.decode_step_string)
        info.update(products=len(T), products_scan=len(R["product_names"]))
        if len(T) != len(R["product_names"]):
            info["mode"] = "verifier default (first PRODUCT string as name)"; return R
        if force_names or not Z.guid_mode(T):
            R["product_names"] = [nm for _, nm, _ in T]
            info["mode"] = "Name (2nd PRODUCT string) -> verifier's ifc2step name mode"; return R
        uu, seen, nong = [], set(), 0
        for gid, nm, _ in T:
            try: u = str(uuid.UUID(ifcopenshell.guid.expand(gid))) if Z._GUID.match(gid) else None
            except Exception: u = None
            if u is None:                                   # not an IFC GlobalId: can never match an element (counted extra)
                nong += 1; u = str(uuid.uuid5(uuid.NAMESPACE_OID, "z3v-non-guid:" + gid + ":" + nm))
            if u not in seen: seen.add(u); uu.append(u)
        R["uuids"] = uu; R["product_names"] = [nm for _, nm, _ in T]
        info.update(mode="GlobalId (first PRODUCT string; ifc2step5/6 convention) -> verifier's exact GlobalId mode",
                    non_guid_products=nong, duplicate_guid_products=len(T) - len(uu))
        return R
    V.scan = scan
    return info


def group_missing(a):
    """attribution rows -> [{what, ids, count, cause}] (cap 200) + all rows for the CSV"""
    rows = [dict(kind="missing_ifc_element", issue="missing", **r) for r in a.get("missing", [])] + \
           [dict(kind="step_part", **r) for r in a.get("parts", [])]
    g = collections.OrderedDict()
    for r in a.get("missing", []):
        k = ("missing", r["cause_class"], r["ifc_type"], r["cause"])
        g.setdefault(k, []).append(r.get("ifc_globalid"))
    for r in a.get("parts", []):
        k = (r["issue"], r["cause_class"], r.get("ifc_type"), r["cause"])
        g.setdefault(k, []).append(r.get("ifc_globalid") or r.get("step_name"))
    out = []
    for (issue, cc, typ, cause), ids in sorted(g.items(), key=lambda kv: (kv[0][1] in ("BY_DESIGN", "SOURCE"), -len(kv[1]))):
        what = (f"{len(ids)} {typ or 'element'} not in the STEP" if issue == "missing" else f"{len(ids)} STEP part(s) {issue} ({typ or 'unidentified'})")
        out.append(dict(what=f"{what}: {cause}", ids=[x for x in ids if x][:50], count=len(ids), cause=CAUSE.get(cc, "unclassified")))
    return out[:200], rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--step", required=True); ap.add_argument("--source", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--id", required=True); ap.add_argument("--workdir", required=True)
    ap.add_argument("--threads", type=int, default=int(os.environ.get("Z3V_THREADS", "2")))
    ap.add_argument("--step-geom-max", type=float, default=None); ap.add_argument("--ifc-geom-max", type=float, default=None)
    a = ap.parse_args()
    for k in ("step", "source", "out", "workdir"): setattr(a, k, os.path.abspath(getattr(a, k)))   # the verifier's workers run elsewhere
    t0 = time.time(); os.makedirs(a.workdir, exist_ok=True)
    doc = dict(verifier="ifc-step-verifier", adapter=Z.ADAPTER_VERSION, tier="n/a", id=a.id)
    full = None; miss_rows = None
    try:
        from ifcstepverify import VERSION, config as C
        doc["verifier_version"] = f"ifcstepverify {VERSION} rules {C.RULES_VERSION}"
        notes = []
        if len(a.id) == 64:
            got = Z.sha256_file(a.source)
            if got != a.id:
                raise SystemExit(f"source sha256 {got[:16]} != id {a.id[:16]}: wrong source file")
        src, un = unpack(a.source, a.workdir)
        if un: notes.append(f"source {un}")
        src, fx = Z.fix_schema(src, a.workdir)
        if fx: notes.append(f"source {fx}")
        if src.lower().endswith(".ifcxml"):
            doc.update(verdict="CANNOT_VERIFY", evidence="integrity", findings=[dict(code="Z_SOURCE_IFCXML", level="WARN", cause="unclassified", count=None,
                       detail="source is ifcXML: the verifier reads SPF only (our worker converts it with ifcxml2spf first)")], missing=[])
            raise StopIteration
        sinfo = install_scan_adapter()
        from ifcstepverify.verify import verify, write
        kw = dict(threads=a.threads, cand_workers=1)
        if a.step_geom_max: kw["step_geom_max"] = a.step_geom_max
        if a.ifc_geom_max: kw["ifc_geom_max"] = a.ifc_geom_max
        try:
            res, run = verify(a.step, [src], **kw)
        except Exception as e:
            if not sinfo.get("mode", "").startswith("GlobalId"): raise
            notes.append(f"GlobalId mode raised {type(e).__name__}: {str(e)[:120]}; re-run in name mode")
            sinfo = install_scan_adapter(force_names=True)
            res, run = verify(a.step, [src], **kw)
        full = {"result": res, "run": run, "adapter": {"scan": sinfo, "notes": notes}}
        findings = [dict(code=r["code"], level=r["level"], cause=CAUSE.get(r["cause_class"], "unclassified"), cause_orig=r["cause_class"],
                         count=r.get("count"), detail=r["message"]) for r in res["reasons"]]
        verdict = {"OUT_OF_SCOPE": "CANNOT_VERIFY"}.get(res["verdict"], res["verdict"])
        srcs = res.get("source") or {}
        cand_err = [c.get("error") for c in srcs.get("candidates", []) if c.get("error")]
        if not srcs.get("best") and cand_err:
            verdict = "CANNOT_VERIFY"; notes.append(f"the source IFC could not be read by IfcOpenShell {doc.get('ifcopenshell', '')}: {cand_err[0][:200]}")
        g = res.get("geometry") or {}
        evidence = ("element_match" if srcs.get("best") and res.get("attribution") is not None else "integrity")
        if evidence == "element_match" and (g.get("skipped") or g.get("error") or not g.get("summary")):
            notes.append("STEP geometry not analysed (element match only)")
        a_ = res.get("attribution") or {}
        missing, miss_rows = group_missing(a_)
        best = srcs.get("best") or {}
        doc.update(verdict=verdict, evidence=evidence, findings=findings, missing=missing, notes=notes,
                   match=dict(method=res.get("match_method") if not sinfo.get("mode", "").startswith("GlobalId") else sinfo["mode"],
                              step_elements=res.get("step_elements"), overlap=best.get("overlap"), precision=best.get("precision"),
                              missing_in_step=best.get("missing_in_step"), extra_in_step=best.get("extra_in_step"),
                              physical_elements=best.get("physical_elements"), mapping=a_.get("mapping")),
                   volume_ratio=res.get("volume_ratio"), bbox_ratio=res.get("bbox_ratio"),
                   geometry={k: v for k, v in (g.get("summary") or {}).items() if k != "bbox_dims_mm"} or ({"skipped": g.get("skipped")} if g.get("skipped") else None),
                   result_digest=res.get("result_digest"), versions=res.get("versions"))
    except StopIteration:
        pass
    except SystemExit as e:
        doc.update(verdict="ERROR", evidence="integrity", findings=[dict(code="Z_INPUT", level="FAIL", cause="unclassified", count=None, detail=str(e))], missing=[])
    except Exception as e:
        doc.update(verdict="ERROR", evidence="integrity", findings=[dict(code="Z_EXCEPTION", level="FAIL", cause="unclassified", count=None,
                   detail=f"{type(e).__name__}: {str(e)[:300]}")], missing=[], trace=traceback.format_exc()[-2000:])
    ok, block = Z.class1_gate(doc["verdict"], doc.get("findings", []))
    m, n = Z.index_reasons("ifc", doc["verdict"], block) if not ok else ([], [])
    doc.update(class1_ok=ok, index_missing=m, index_needed_to_fix=n, runtime_s=round(time.time() - t0, 1), peak_gb=Z.peak_gb())
    Z.write_out(a.out, doc, miss_rows, CSV_COLS, full)
    print(json.dumps({k: doc.get(k) for k in ("id", "verdict", "evidence", "class1_ok", "runtime_s", "peak_gb")} |
                     {"codes": [f"{f['level'][0]}:{f['code']}:{f['cause']}" + (f"x{f['count']}" if f.get("count") else "") for f in doc.get("findings", [])]}))


if __name__ == "__main__":
    main()
