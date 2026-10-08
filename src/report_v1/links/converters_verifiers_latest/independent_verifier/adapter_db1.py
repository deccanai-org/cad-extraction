#!/usr/bin/env python3
"""Zenitude-data-3 Tekla DB1 -> STEP verification job: the teammate's db1-step-verifier (db1stepverify, shipped
unchanged) run on one data-3 model.

  PY adapter_db1.py --step <local STEP> --source <local .db1> --out <result.json> --id <sha256> --workdir <dir>
                    [--record <local data-3 result JSON>] [--truth-dir <dir with candidate Tekla IFC exports>]
                    [--kit-dir <DB1 kit dir>] [--decoder-python <python for the decoder, e.g. /opt/conv/ifc84/bin/python>]
                    [--step-geom-max 3e9] [--db1-repro-max 2.5e8] [--threads 2] [--no-repro] [--no-truth]

Stages and what the adapter changes (data sources only; codes, thresholds and the verdict rules are the verifier's):
  record     our data-3 record (_state/conv/db1/results/<id>.json: --record, else read from bim) mapped onto the
             verifier's record fields (key=input_key, db1_bytes=in_bytes, out_bytes, convert, excluded_elements, ...);
             CURRENT_CODE = the kit's CODE (z3-db1-2026-10-01r)
  input      the local .db1 (staged by the worker): sha256 == id, Xsteel banner == record engine
  step       local STEP; product names = the 2nd PRODUCT string (our writers put the GlobalId first, the profile second)
  geometry   unchanged (OpenCascade per part)
  reproduce  OFF by default (--repro to run it; owner 2026-10-02: it is our own decoder, not independent). When on, OUR decoder: the data-3 DB1 kit (code r) convert_one.py, exactly as db1/worker.py runs it
             (z3v_db1_repro.py), meshed and matched by the verifier's own code
  truth      Tekla IFC exports staged in --truth-dir (the worker stages truth_map.json candidates: same folder / IFC/ /
             ifc/ / Output/ / parent of the .db1 in any of its archive paths - the verifier's sibling rule); the
             verifier's own Tekla-header filter, alignment and matching decide
  render     unchanged (PNG sheets next to the result);  vlm  not run (no API spend)
Verdict: the verifier's. CANNOT_VERIFY only when the STEP geometry could not be analysed and no Tekla export matched.
Evidence: external_truth (Tekla export matched, recall >= 60 %) > independent_decode (--repro, >= 98 % reproduced) > integrity.
Cause mapping: PIPELINE->pipeline, DECODER->decoder, SOURCE->source, BY_DESIGN->by_design, EVIDENCE->unclassified.
One documented re-attribution: W_PRODUCT_SOLID_COUNT (products != faceted solids) is by_design only when EVERY product
whose solid count is not 1 is an IfcMechanicalFastener (our bolt-group products carry one solid per bolt / nut /
washer); otherwise it stays pipeline."""
import os, sys, re, json, time, argparse, shutil, hashlib, glob, traceback, subprocess
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import z3v_common as Z

B = "bim-proprietary-data"; ROOT = "cad-disk-extract/zenitude-data-3"
KIT_BUCKET = "annotationprod"; KIT_PREFIX = "cad-disk-extract/_control/z3conv/db1/"
CAUSE = {"PIPELINE": "pipeline", "DECODER": "decoder", "SOURCE": "source", "BY_DESIGN": "by_design", "EVIDENCE": "unclassified"}
EVID = {"tekla_export": "external_truth", "reproduced": "independent_decode", "geometry": "integrity", "integrity": "integrity"}
CSV_COLS = ["kind", "type", "name", "profile", "guid", "step_name", "part", "dist_mm", "vol_ratio", "centroid"]
KIT_FILES_SKIP = (".sh", "canary.json", "env.json", "hold", "redo_ids.json")


def fetch_kit(cache):
    """the DB1 conversion kit (code r) from annotationprod _control/z3conv/db1/ (top level), cached by worker.py ETag"""
    s3 = Z.s3_client()
    objs = [o for p in s3.get_paginator("list_objects_v2").paginate(Bucket=KIT_BUCKET, Prefix=KIT_PREFIX, Delimiter="/") for o in p.get("Contents", [])]
    w = [o for o in objs if o["Key"].endswith("/worker.py")][0]
    d = os.path.join(cache, "db1kit-" + w["ETag"].strip('"')[:12])
    if not os.path.exists(os.path.join(d, ".complete")):
        os.makedirs(d, exist_ok=True)
        for o in objs:
            nm = o["Key"].rsplit("/", 1)[1]
            if nm and not nm.endswith(KIT_FILES_SKIP):
                s3.download_file(KIT_BUCKET, o["Key"], os.path.join(d, nm))
        open(os.path.join(d, ".complete"), "w").write("ok")
    return d


def kit_code(kit):
    m = re.search(r"^CODE\s*=\s*'([^']+)'", open(os.path.join(kit, "worker.py")).read(), re.M)
    return m.group(1) if m else None


def kit_digest(kit):
    h = hashlib.sha256()
    for f in ("convert_one.py", "db1step.py", "db1dec.py", "db1old.py", "db1bolts.py", "db1bolts2.py", "db1prof.py", "fittings.py", "attrlink.py",
              "layouts.json", "tekla_profiles.json", "tekla_profiles_overlay.json", "bolt_catalog.json", "tekla_bolt_assemblies.json"):
        p = os.path.join(kit, f)
        if os.path.exists(p): h.update(f.encode()); h.update(open(p, "rb").read())
    return h.hexdigest()[:16]


def map_record(r, sha):
    """our data-3 result record -> the verifier's db1-v2 record fields"""
    if not r: return dict(error="no data-3 result record")
    v = r.get("validate") or {}
    return dict(status=r.get("status"), code=r.get("code"), engine=r.get("engine"), key="z3v://input/" + sha, db1_bytes=r.get("in_bytes"),
                out_bytes=r.get("out_bytes") or (r.get("step") or {}).get("bytes"), old_status=None, arc_writer=r.get("arc_writer"), arc_check=None,
                excluded_elements=r.get("excluded_elements"), convert=r.get("convert"), markers=v.get("markers"), flavour_ok=v.get("flavour_ok"),
                readback=v.get("read_status"), finished=r.get("finished"), error=r.get("error") or (r.get("reason") if r.get("status") != "ok" else None),
                step_stats=r.get("step_stats"), z3_input_key=r.get("input_key"), z3_out_key=r.get("out_key"))


def install(a, rec_mapped, sha, kit, notes):
    """point db1stepverify at local files + our decoder (module-attribute patches; the verifier's code is unchanged)"""
    from db1stepverify import config as C, s3io, reproduce, geometry, ifcmesh, stepfile, verify as V
    C.BUCKET = B; C.SRC_BUCKET = B
    C.STEP_PREFIX = f"{ROOT}/conversions/db1-step/"; C.RESULTS_PREFIX = f"{ROOT}/_state/conv/db1/results/"
    C.CURRENT_CODE = (kit_code(kit) if kit else None) or os.environ.get("Z3V_DB1_CODE", "z3-db1-2026-10-01r")
    local = {f"{C.STEP_PREFIX}{sha}.stp": a.step, rec_mapped.get("key"): a.source}
    meta = {}
    if a.truth_dir and os.path.isdir(a.truth_dir):
        mp = os.path.join(a.truth_dir, "truth_meta.json")
        meta = json.load(open(mp)) if os.path.exists(mp) else {}
    def head(bucket, key):
        p = local.get(key)
        if p and os.path.exists(p): return dict(bytes=os.path.getsize(p), etag=None, modified=None)
        return dict(error="NoSuchKey")
    def download(bucket, key, path):
        p = local[key]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.abspath(p) == os.path.abspath(path): return path
        if os.path.lexists(path): os.remove(path)
        os.symlink(os.path.abspath(p), path)
        return path
    def sibling_ifcs(key, max_bytes=C.TRUTH_IFC_MAX_BYTES):
        out = []
        for p in sorted(glob.glob(os.path.join(a.truth_dir, "*.ifc"))) if a.truth_dir else []:
            sz = os.path.getsize(p)
            if not (10_000 < sz <= max_bytes): continue
            k = "z3v://truth/" + os.path.basename(p)
            fp, fx = Z.fix_schema(p, os.path.join(a.workdir, "truth_fixed"))
            local[k] = fp
            if fx: notes.setdefault("truth_input_fix", {})[os.path.basename(p)] = fx
            m = meta.get(os.path.basename(p)) or {}
            out.append(dict(key=k, bytes=sz, same_folder=m.get("scope", "same_folder") == "same_folder", **ifcmesh.ifc_head(fp)))
        return sorted(out, key=lambda x: (not x["same_folder"], not x["tekla"], -x["bytes"]))
    s3io.record = lambda s: rec_mapped
    s3io.head = head; s3io.download = download; s3io.sibling_ifcs = sibling_ifcs
    s3io.locate_in_source_bucket = lambda key, listing_dir=None: dict(found=bool(rec_mapped.get("z3_input_key")), bim_key=rec_mapped.get("z3_input_key"),
                                                                      how="data-3 record input_key (staged locally by the worker)")
    # STEP product names: the 2nd PRODUCT string (profile) when the 1st is a GlobalId (ifc2step5/6 convention)
    orig_scan = stepfile.scan
    def scan(path):
        R = orig_scan(path)
        if R.get("kind") == "step":
            T = Z.product_triples(path, stepfile.decode_step_string)
            if len(T) == len(R["product_names"]) and Z.guid_mode(T):
                R["product_names"] = [t[1] for t in T]; notes["names"] = "2nd PRODUCT string (1st is the IFC GlobalId)"
                notes["_descs"] = [t[2] for t in T]
        return R
    V.scan = scan
    # geometry: keep the per-part list for the W_PRODUCT_SOLID_COUNT attribution
    orig_geo = geometry.analyze_step
    def analyze_step(path, *aa, **kw):
        g = orig_geo(path, *aa, **kw); notes["_parts"] = [(p["part"], p.get("solids")) for p in g.get("parts", [])]; return g
    geometry.analyze_step = analyze_step
    # reproduce: our decoder
    digest = kit_digest(kit) if kit else None
    def run(db1_path, engine, work_dir, cache_dir, timeout=4 * 3600):
        os.makedirs(work_dir, exist_ok=True)
        out = os.path.join(work_dir, "repro_elements.json")
        cmd = [sys.executable, os.path.join(HERE, "z3v_db1_repro.py"), db1_path, os.path.join(work_dir, "repro.ifc"), kit, engine or "", out, a.decoder_python or ""]
        t0 = time.time()
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=dict(os.environ, Z3V_THREADS=str(a.threads)))
            rc = p.returncode; tail = (p.stdout + p.stderr)[-1500:]
        except subprocess.TimeoutExpired:
            return dict(status="timeout", secs=round(time.time() - t0, 1), decoder_digest=digest, decoder_code=C.CURRENT_CODE)
        if rc != 0 or not os.path.exists(out):
            return dict(status="error", rc=rc, log_tail=tail, secs=round(time.time() - t0, 1), decoder_digest=digest, decoder_code=C.CURRENT_CODE)
        r = json.load(open(out)); r["secs"] = round(time.time() - t0, 1); r["decoder_digest"] = digest; r["decoder_code"] = C.CURRENT_CODE
        return r
    reproduce.run = run
    return C


def stage_truth(truth_map, sha, d, notes):
    """download the Tekla export candidates of this model (truth_map.json: {db1 id: [{ifc_id, input_key, scope, size, path}]})
    from bim into d (+ truth_meta.json); the verifier's own filters (size, Tekla header, alignment) decide what is used"""
    tm = json.load(open(truth_map)); ents = tm.get(sha) or []
    os.makedirs(d, exist_ok=True); meta = {}
    s3 = Z.s3_client() if ents else None
    for e in ents:
        nm = e["ifc_id"][:16] + ".ifc"; p = os.path.join(d, nm)
        if not (10_000 < (e.get("size") or 0) <= 400e6) or not e.get("input_key"):
            notes.setdefault("truth_skipped", []).append(dict(ifc_id=e["ifc_id"], why="size outside 10 kB..400 MB or no stored copy")); continue
        if not os.path.exists(p):
            try:
                s3.download_file(B, e["input_key"], p + ".part"); os.replace(p + ".part", p)
            except Exception as ex:
                notes.setdefault("truth_skipped", []).append(dict(ifc_id=e["ifc_id"], why=f"download {type(ex).__name__}")); continue
            if Z.sha256_file(p) != e["ifc_id"]:
                os.remove(p); notes.setdefault("truth_skipped", []).append(dict(ifc_id=e["ifc_id"], why="sha256 mismatch")); continue
        meta[nm] = dict(scope=e.get("scope"), path=e.get("path"), ifc_id=e["ifc_id"])
    json.dump(meta, open(os.path.join(d, "truth_meta.json"), "w"), indent=1)
    notes["truth_staged"] = len(meta)
    return d


def solid_count_by_design(notes, res):
    """True when every product whose solid count != 1 is an IfcMechanicalFastener (bolt group) product"""
    parts, descs = notes.get("_parts"), notes.get("_descs")
    if not parts or not descs or len(descs) != len(parts): return False, "per-product classes unavailable"
    odd = [(i, n) for i, n in parts if n != 1]
    bad = [(i, n) for i, n in odd if not descs[i - 1].startswith("IfcMechanicalFastener")]
    nb = sum(1 for d in descs if d.startswith("IfcMechanicalFastener"))
    if bad: return False, f"{len(bad)} non-fastener products with != 1 solid (e.g. part {bad[0][0]}: {bad[0][1]} solids, {descs[bad[0][0] - 1][:40]})"
    return True, f"all {len(odd)} products with != 1 solid are bolt-group products (IfcMechanicalFastener: {nb}); every other product is 1 solid"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--step", required=True); ap.add_argument("--source", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--id", required=True); ap.add_argument("--workdir", required=True)
    ap.add_argument("--record"); ap.add_argument("--truth-dir"); ap.add_argument("--truth-map", help="truth_map.json (from this kit): the adapter stages this model's Tekla export candidates from bim"); ap.add_argument("--kit-dir"); ap.add_argument("--decoder-python")
    ap.add_argument("--step-geom-max", type=float, default=3e9); ap.add_argument("--db1-repro-max", type=float, default=2.5e8)
    ap.add_argument("--threads", type=int, default=int(os.environ.get("Z3V_THREADS", "2")))
    ap.add_argument("--repro", action="store_true", help="also run the reproduce stage with our decoder (off by default: owner 2026-10-02, it is our own decoder)")
    ap.add_argument("--no-truth", action="store_true")
    a = ap.parse_args()
    for k in ("step", "source", "out", "workdir", "record", "truth_dir", "kit_dir", "truth_map"):
        if getattr(a, k): setattr(a, k, os.path.abspath(getattr(a, k)))
    t0 = time.time(); os.makedirs(a.workdir, exist_ok=True)
    doc = dict(verifier="db1-step-verifier", adapter=Z.ADAPTER_VERSION, tier="n/a", id=a.id)
    full = None; rows = None; notes = {}
    try:
        from db1stepverify import VERSION, config as C0
        doc["verifier_version"] = f"db1stepverify {VERSION} rules {C0.RULES_VERSION}"
        sha = a.id
        rec = json.load(open(a.record)) if a.record else Z.get_json_s3(B, f"{ROOT}/_state/conv/db1/results/{sha}.json")
        recm = map_record(rec, sha)
        kit = a.kit_dir or (fetch_kit(os.path.join(os.path.dirname(a.workdir.rstrip("/")), "_z3v_cache")) if a.repro else None)
        if a.truth_map and not a.truth_dir:
            a.truth_dir = stage_truth(a.truth_map, sha, os.path.join(a.workdir, "truth"), notes)
        C = install(a, recm, sha, kit, notes)
        from db1stepverify.verify import verify
        vout = os.path.join(a.workdir, "vout")
        res, run = verify(sha, a.workdir, vout, do_repro=a.repro, do_truth=not a.no_truth, vlm_mode="none",
                          step_geom_max=a.step_geom_max, db1_repro_max=a.db1_repro_max, keep_files=False, log=lambda *x: None)
        findings = []
        for f in res["findings"]:
            cause = CAUSE.get(f["cause"], "unclassified"); extra = {}
            if f["code"] == "W_PRODUCT_SOLID_COUNT":
                ok, why = solid_count_by_design(notes, res)
                extra["adapter_attribution"] = why
                if ok: cause = "by_design"
            findings.append(dict(code=f["code"], level=f["level"], cause=cause, cause_orig=f["cause"], count=f.get("count"), detail=f["message"],
                                 **{k: v for k, v in f.items() if k in ("examples", "top", "near", "missing", "by_profile")}, **extra))
        verdict = res["verdict"]; evidence = EVID.get(res.get("evidence"), "integrity")
        rep = res.get("reproduce") or {}; tr = res.get("truth") or {}
        g0 = res.get("geometry") or {}
        if verdict != "FAIL" and (not g0 or g0.get("skipped") or g0.get("error")) and tr.get("status") != "matched":
            verdict = "CANNOT_VERIFY"
            doc.setdefault("notes", []).append(f"STEP geometry not analysed ({g0.get('skipped') or g0.get('error')}) and no Tekla export matched")
        if tr.get("status") != "matched":
            doc.setdefault("notes", []).append(f"no external truth (Tekla export: {tr.get('status')}): verdict rests on the record, STEP and geometry checks")
        missing, rows = [], []
        if tr.get("status") == "matched":
            m = tr["match"]
            nmiss = m["b"] - m["matched"] - m["near"]
            if nmiss: missing.append(dict(what=f"{nmiss} of {m['b']} Tekla export elements have no STEP part nearby (recall {m['recall_b']:.1%})",
                                          ids=[x["guid"] for x in tr.get("missing_examples", [])], count=nmiss, cause="decoder"))
            if m["near"]: missing.append(dict(what=f"{m['near']} Tekla export elements in place within {C.TRUTH_NEAR_DIST_MM:.0f} mm but with another volume",
                                              ids=[x.get("profile") for x in tr.get("near_examples", [])], count=m["near"], cause="decoder"))
            rows += [dict(kind="truth_missing", **{k: x.get(k) for k in ("type", "name", "profile", "guid", "centroid")}) for x in tr.get("missing_examples", [])]
            rows += [dict(kind="truth_near", **{k: x.get(k) for k in ("type", "profile", "step_name", "dist_mm", "vol_ratio", "centroid")}) for x in tr.get("near_examples", [])]
        if rep.get("match"):
            m = rep["match"]; nun = m["a"] - m["matched"]
            if nun: missing.append(dict(what=f"{nun} of {m['a']} STEP parts not rebuilt in place by the decoder re-run (code {rep.get('decoder_code')})",
                                        ids=[x.get("name") for x in rep.get("unreproduced_examples", [])], count=nun, cause="pipeline"))
            rows += [dict(kind="repro_unmatched", **{k: x.get(k) for k in ("part", "name", "centroid")}) for x in rep.get("unreproduced_examples", [])]
        g = res.get("geometry") or {}
        doc.update(verdict=verdict, evidence=evidence, evidence_orig=res.get("evidence"), findings=findings, missing=missing[:200],
                   reproduce={k: rep.get(k) for k in ("status", "skipped", "decoder_code", "decoder_digest", "elements", "match", "same_counts_as_record",
                                                       "name_agreement", "secs", "full_discovery", "decoder_python")},
                   truth={k: tr.get(k) for k in ("status", "ifc", "elements", "name_overlap", "match", "recall_with_near", "recall_by_type",
                                                  "prof_agreement", "align", "in_place_other_volume", "displacement")} | {"candidates": len(tr.get("candidates") or [])},
                   geometry={k: g.get(k) for k in ("parts", "kinds", "extent_mm", "stray_parts", "coincident_duplicates", "brepcheck_checked",
                                                    "brepcheck_invalid", "volume_m3", "skipped", "error")},
                   record_code=recm.get("code"), current_code=C.CURRENT_CODE, stage_errors=res.get("stage_errors"),
                   result_digest=res.get("result_digest"), versions=res.get("versions"), stages_s=run.get("stages"))
        doc.setdefault("notes", []).extend([f"product names: {notes['names']}"] if notes.get("names") else [])
        if notes.get("truth_input_fix"): doc["truth_input_fix"] = notes["truth_input_fix"]
        if notes.get("truth_staged") is not None: doc["truth_staged"] = notes["truth_staged"]
        if notes.get("truth_skipped"): doc["truth_skipped"] = notes["truth_skipped"]
        full = {"result": res, "run": run}
        for p in glob.glob(os.path.join(vout, "*.png")):
            dst = (a.out[:-5] if a.out.endswith(".json") else a.out) + "." + os.path.basename(p).split("_", 1)[1]
            shutil.copyfile(p, dst); doc.setdefault("renders", []).append(os.path.basename(dst))
    except Exception as e:
        doc.update(verdict="ERROR", evidence="integrity", findings=[dict(code="Z_EXCEPTION", level="FAIL", cause="unclassified", count=None,
                   detail=f"{type(e).__name__}: {str(e)[:300]}")], missing=[], trace=traceback.format_exc()[-2000:])
    ok, block = Z.class1_gate(doc["verdict"], doc.get("findings", []))
    m, n = Z.index_reasons("db1", doc["verdict"], block) if not ok else ([], [])
    doc.update(class1_ok=ok, index_missing=m, index_needed_to_fix=n, runtime_s=round(time.time() - t0, 1), peak_gb=Z.peak_gb())
    Z.write_out(a.out, doc, rows, CSV_COLS, full)
    print(json.dumps({k: doc.get(k) for k in ("id", "verdict", "evidence", "class1_ok", "runtime_s", "peak_gb")} |
                     {"codes": [f"{f['level'][0]}:{f['code']}:{f['cause']}" for f in doc.get("findings", [])]}))


if __name__ == "__main__":
    main()
