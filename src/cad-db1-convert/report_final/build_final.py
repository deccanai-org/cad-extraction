"""Final outcome report for the CAD STEP work (READ-ONLY against S3; bim profile is enough).
  build_final.py            -> preliminary (pending counted separately)
  build_final.py --final    -> refuses while any DB1/IFC job is not final or packaging markers are missing
Outputs in ./out/: db1_not_converted.csv, ifc_not_converted.csv, repairs.csv, summary.json,
conversions.json (public aggregates only: no paths, no archive or project names)."""
import csv, collections, json, os, sys, time, threading
from concurrent.futures import ThreadPoolExecutor
import boto3
from botocore.config import Config

B = "annotationprod"; R = "cad-disk-extract"
HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, "out"); os.makedirs(OUT, exist_ok=True)
FINAL = "--final" in sys.argv
SESS = boto3.Session(profile_name=os.environ.get("AWS_PROFILE", "bim")); TL = threading.local()
def s3():
    c = getattr(TL, "c", None)
    if c is None:
        c = TL.c = SESS.client("s3", region_name="ap-south-1", config=Config(max_pool_connections=64, retries={"max_attempts": 10, "mode": "standard"}))
    return c
def getj(k):
    for _ in range(4):
        try: return json.loads(s3().get_object(Bucket=B, Key=k)["Body"].read())
        except s3().exceptions.NoSuchKey: return None
        except Exception: time.sleep(1)
def keys(pre): return [o["Key"] for pg in s3().get_paginator("list_objects_v2").paginate(Bucket=B, Prefix=pre) for o in pg.get("Contents", [])]
def pmap(fn, xs, n=64):
    with ThreadPoolExecutor(n) as ex: return list(ex.map(fn, xs))

# ---------------------------------------------------------------- DB1
CODE = "db1-2026-09-25g"
_K = {"empty_model", "no_member_layout", "no_resolvable_members", "bad_output", "deferred_layout"}
KEEP = {c: _K for c in ("db1-2026-09-25b", "db1-2026-09-25c", "db1-2026-09-25d", "db1-2026-09-25e")}
KEEP["db1-2026-09-25f"] = _K | {"ok", "suspect_orientation", "suspect_attr_link", "convert_error"}
def db1_final(r):
    """the worker's own rule (db1_worker.done_now): results the worker will still re-run are pending"""
    if not r: return False
    if r.get("code") == CODE and r.get("status") == "step_fail":
        if not r.get("writer"): return False
        if r.get("arc_writer") and r.get("step_rc") in (-11, 139, 124, 125) and not r.get("rescue"): return False
    if not r.get("arc_writer") and r.get("code") in (CODE, "db1-2026-09-25f") and (
            (r.get("status") == "ok" and ((r.get("convert") or {}).get("sources") or {}).get("contour_plate", 0) > 0
             and (r.get("layout") or {}).get("poly_ch")) or (r.get("status") == "step_fail" and r.get("code") == CODE)):
        return False
    return r.get("code") == CODE or r.get("status") in KEEP.get(r.get("code"), ())
DB1_REASON = {
    "deferred_layout": ("layout_not_decodable", "Part-table layout not identified by the decoder (large models); no STEP written rather than a guessed one"),
    "empty_model": ("empty_model", "Model holds no modelled parts (empty, template or environment model)"),
    "no_member_layout": ("no_part_table", "No part table found (old-format file, template or profile/standard-parts library)"),
    "suspect_orientation": ("held_back_orientation", "Held back: fewer than 90% of members lie along their own reference line (orientation link not trusted)"),
    "suspect_attr_link": ("held_back_attribute_link", "Held back: parts named COLUMN are not vertical (attribute link not trusted)"),
    "no_resolvable_members": ("no_buildable_profiles", "Parts found but none has a profile the writer can build"),
    "convert_error": ("corrupt_source", "Source file is corrupt (compressed stream fails its CRC)"),
    "bad_output": ("no_body_geometry", "Conversion ran but produced no solid body geometry"),
    "step_fail": ("step_writer_failed", "IFC to STEP stage failed"),
    "worker_error": ("worker_error", "Worker error"),
    "no_version_banner": ("not_a_tekla_model", "No Tekla version banner: not a recognisable Tekla model file"),
}
def db1_detail(st, r):
    c = (r or {}).get("convert") or {}; lay = (r or {}).get("layout") or {}
    if st == "deferred_layout": return f"decompressed {c.get('mb')} MB; layouts tried {len(lay.get('tried') or [])}"
    if st == "suspect_orientation": return f"members {c.get('members')}; axis agreement {c.get('axis_agreement')}"
    if st == "suspect_attr_link": return f"name check {json.dumps(c.get('name_check'))}"
    if st == "no_resolvable_members": return "unresolved profiles " + ", ".join(f"{p} x{n}" for p, n in (c.get("unresolved_top") or [])[:6])
    if st == "convert_error": return (c.get("trace") or "").strip().splitlines()[-1][:160] if c.get("trace") else ""
    if st == "bad_output": return f"written {c.get('written')}; sources {json.dumps(c.get('sources'))}"
    if st in ("step_fail", "worker_error"): return ((r or {}).get("error") or (r or {}).get("log_tail") or "")[-200:].replace("\n", " ")
    if st == "no_member_layout": return f"format {lay.get('format')}; points {lay.get('points')}; parts {lay.get('parts')}"
    if st == "empty_model": return f"decompressed {c.get('mb')} MB"
    return ""
def archive_of(key):
    p = key.split("/")
    return "/".join(p[1:3]) if len(p) > 3 else key

jobs = json.loads(s3().get_object(Bucket=B, Key=f"{R}/_control/db1-v2/db1_jobs.json")["Body"].read())["jobs"]
res = pmap(lambda j: getj(f"{R}/_state/db1-v2/results/{j['sha']}.json"), jobs, 96)
db1_rows = []; db1_st = collections.Counter(); byv = collections.defaultdict(collections.Counter); pending = []
ok_recs = []
for j, r in zip(jobs, res):
    if j["engine"] in ("None", None): st = "no_version_banner"
    elif db1_final(r): st = r["status"]
    else: st = "pending"; pending.append(j["sha"])
    db1_st[st] += 1; byv[j["engine"]]["files"] += 1
    if st == "ok":
        byv[j["engine"]]["converted"] += 1; ok_recs.append(r); continue
    byv[j["engine"]]["not_converted"] += 1
    reason, label = DB1_REASON.get(st, (st, st))
    db1_rows.append(dict(reason=reason, reason_text=label, tekla_version=j["engine"], source_archive=archive_of(j["key"]),
                         path_in_archive="/".join(j["key"].split("/")[3:]), db1_bytes=j["bytes"], sha256=j["sha"],
                         status=st, detail=db1_detail(st, r), decoder_code=(r or {}).get("code")))
db1_rows.sort(key=lambda x: (x["reason"], x["tekla_version"], x["source_archive"], x["path_in_archive"]))
with open(os.path.join(OUT, "db1_not_converted.csv"), "w", newline="") as fh:
    cw = csv.DictWriter(fh, fieldnames=list(db1_rows[0].keys())); cw.writeheader(); cw.writerows(db1_rows)
parts_written = sum((r.get("convert") or {}).get("written", 0) for r in ok_recs)
checks = {"ap214_faceted_brep_flavour_ok": sum(1 for r in ok_recs if r.get("flavour_ok")),
          "occ_readback_ok": sum(1 for r in ok_recs if (r.get("readback") or {}).get("read_status") == "ok"),
          "occ_readback_skipped_output_over_64mb": sum(1 for r in ok_recs if (r.get("readback") or {}).get("skipped")),
          "parts_dropped_axis_mismatch": sum((r.get("convert") or {}).get("axis_mismatch_dropped") or 0 for r in ok_recs),
          "parts_dropped_implausible_profile": sum(((r.get("convert") or {}).get("skipped") or {}).get("implausible_profile", 0) for r in ok_recs),
          "max_abs_coordinate_mm": max((max(abs(v) for v in (r.get("step_stats") or {}).get("bbox") or [0])) for r in ok_recs) if ok_recs else None}

# ---------------------------------------------------------------- IFC
ij = json.loads(s3().get_object(Bucket=B, Key=f"{R}/_control/ifc-step/ifc_jobs.json")["Body"].read()); ij = ij["jobs"] if isinstance(ij, dict) else ij
ires = pmap(lambda j: getj(f"{R}/_state/ifc-step/results/{j['id']}.json"), ij, 96)
idef = pmap(lambda j: getj(f"{R}/_state/ifc-step/deferred/{j['id']}.json"), [j for j, r in zip(ij, ires) if r is None], 32)
defmap = {j["id"]: d for j, d in zip([j for j, r in zip(ij, ires) if r is None], idef)}
IFC_REASON = {"empty": ("no_geometry", "IFC holds no product geometry (no solids to convert)"),
              "convert_fail": ("converter_failed", "Converter failed on this file (after as-is, header-fix, hybrid and tessellation attempts)"),
              "convert_timeout": ("converter_timeout", "Converter did not finish within 6 h"),
              "unsupported_format": ("not_ifc", "Not an IFC model (CIS/2 structural frame file with an .ifc name)"),
              "worker_error": ("worker_error", "Worker error"), "bad_flavour": ("bad_output", "Output failed the STEP flavour check"),
              "too_large": ("too_large_for_memory", "Needs more memory than a 512 GB host provides"),
              "no_result": ("not_run", "No conversion result")}
DIAG = json.load(open(os.path.join(HERE, "ifc_diagnostics.json")))   # per-file diagnoses from inspecting the inputs
ifc_rows = []; ifc_st = collections.Counter(); ifc_open = []; fixes = collections.Counter(); ifc_ok = []; ifc_reason = collections.Counter()
for j, r in zip(ij, ires):
    st = (r or {}).get("status")
    if st == "ok":
        ifc_st["ok"] += 1; ifc_ok.append(r)
        fx = r.get("input_unzipped") or r.get("input_fix")
        if fx: fixes[fx] += 1
        continue
    if r is None: st = "too_large" if defmap.get(j["id"]) else "no_result"
    if st in ("convert_fail", "convert_timeout", "worker_error", "bad_flavour") and not r.get("finisher"): ifc_open.append(j["id"])
    if r is None and not defmap.get(j["id"]): ifc_open.append(j["id"])
    ifc_st[st] += 1
    reason, label = IFC_REASON.get(st, (st, st))
    if j["id"] in DIAG and DIAG[j["id"]]["reason"] != "repaired_concatenated": reason, label = DIAG[j["id"]]["reason"], DIAG[j["id"]]["text"]
    elif st == "convert_fail" and (r or {}).get("rc") == -11: reason, label = "kernel_crash", "Geometry kernel crashes on this model (segfault); rescue: " + str(((r or {}).get("rescue") or {}).get("result"))
    ifc_reason[reason] += 1
    key = j["key"]; proj = key.split("/dataset/main/")[-1].split("/")[1] if "/dataset/main/" in key else ""
    ifc_rows.append(dict(reason=reason, reason_text=label, project=proj, file=key.rsplit("/", 1)[-1], ifc_bytes=j.get("size"),
                         projects_using=len(j.get("uses") or []), status=st, input_fix=(r or {}).get("input_fix") or (r or {}).get("input_unzipped") or "",
                         detail=((r or {}).get("reason") or ((r or {}).get("log_tail") or "")[-160:]).replace("\n", " "), id=j["id"]))
ifc_rows.sort(key=lambda x: (x["reason"], x["project"], x["file"]))
if ifc_rows:
    with open(os.path.join(OUT, "ifc_not_converted.csv"), "w", newline="") as fh:
        cw = csv.DictWriter(fh, fieldnames=list(ifc_rows[0].keys())); cw.writeheader(); cw.writerows(ifc_rows)
ifc_maxc = max((max(abs(v) for v in ((r.get("stats") or {}).get("bbox") or [0]))) for r in ifc_ok) if ifc_ok else None

# ---------------------------------------------------------------- packaging (plans, markers, verify)
EG = f"{R}/_control/packaging/endgame"
markers = sorted(k.rsplit("/", 1)[1] for k in keys(EG + "/") if "/log" not in k and not k.endswith((".py", ".sh", ".txt")))
def plan(name):
    return getj(f"{R}/_control/packaging/{name}/plan.json") or []
plans = {n: plan(n) for n in ("step_v1_ifc", "step_v1_ifc2", "step_v1_db1", "step_v1_db1_posthoc", "step_v1_db1_posthoc2")}
pk = {}
for n, p in plans.items():
    pk[n] = dict(projects=len(p), step_files_added=sum(len(x.get("adds") or []) for x in p),
                 distinct_converted_sources=len({a["out_key"] for x in p for a in (x.get("adds") or [])}),
                 moved_2d_to_3d=sum(1 for x in p if x.get("move_to_3d")))
# end-of-run corrections (per-project done records written by the operator passes)
def done_recs(name): return [r for r in pmap(getj, [k for k in keys(f"{R}/_control/packaging/{name}/done/") if k.endswith(".json")], 32) if r]
_dd = done_recs("dedup_step"); _es = done_recs("empty_step")
cleanup = dict(step_duplicates_collapsed=sum(len(r.get("dropped") or []) for r in _dd), projects_deduplicated=len(_dd),
               empty_step_removed=sum(len(r.get("removed") or []) for r in _es), projects_with_empty_step=len(_es),
               projects_moved_back_to_2d=sum(1 for r in _es if r.get("result") == "moved_to_2d"),
               missed_copies_placed=json.load(open(os.path.join(OUT, "posthoc_counts.json"))).get("packaged_identity_matches", 0) if os.path.exists(os.path.join(OUT, "posthoc_counts.json")) else None)
COV = json.load(open(os.path.join(OUT, "db1_coverage.json"))) if os.path.exists(os.path.join(OUT, "db1_coverage.json")) else {}
if COV:
    # real STEP per model file: the original pipeline's OK outputs (all outside this run's scope) + this run's OK outputs;
    # the original pipeline's header-only STEP for its failed runs do not count (removed from the dataset)
    COV["models_with_step"] = int(COV.get("old_pipeline_step_ok", 0)) + db1_st.get("ok", 0)
    COV["models_without_step"] = int(COV.get("model_db1_distinct_all", 0)) - COV["models_with_step"]
ver = [getj(k) for k in keys(f"{R}/_control/packaging/verify/") if k.endswith(".json") and "_of_" in k]
vc = collections.Counter()
for v in ver:
    if v: vc.update(v.get("counts", {}))
ext = json.load(open(os.path.join(OUT, "leftovers_extraction.json")))["extraction"]
repairs = [r for r in ifc_ok if r.get("input_fix") == "concatenated_ifc_merged" or r.get("repair")]

summary = dict(generated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), final=FINAL,
    db1=dict(distinct_files=len(jobs), outcomes=dict(db1_st), pending=len(pending), parts_written=parts_written, checks=checks,
             by_version={v: dict(c) for v, c in sorted(byv.items())}, decoder_code=CODE),
    ifc=dict(distinct_files=len(ij), outcomes=dict(ifc_st), not_converted_by_reason=dict(ifc_reason), open=len(ifc_open), recovered_by_input_fix=dict(fixes), max_abs_coordinate_mm=ifc_maxc,
             repaired=[dict(id=r["id"], fix=r.get("input_fix") or ("corrupt_coordinates_guard" if r.get("repair") else None), excluded=len(r.get("excluded_elements") or [])) for r in ifc_ok if r.get("repair") or r.get("input_fix") in ("concatenated_ifc_merged", "kernel_crash_elements_excluded")]),
    packaging=dict(plans=pk, verify=dict(vc), markers=markers, cleanup=cleanup), extraction=ext,
    db1_coverage={k: v for k, v in COV.items()})
json.dump(summary, open(os.path.join(OUT, "summary.json"), "w"), indent=1)

if FINAL:
    need = {"db1pack_done_mum", "db1pack_done_hyd", "fleet_released", "ifc2_done", "retag_done_mum", "retag_done_hyd", "verify_done_mum", "verify_done_hyd", "endgame_done"}
    miss = need - set(markers)
    if pending or ifc_open or miss:
        sys.exit(f"refusing --final: db1 pending {len(pending)}, ifc open {len(ifc_open)}, missing markers {sorted(miss)}")

# ---------------------------------------------------------------- dataset counts straight from project.json
# (used when the end-game's full verification has not run yet; after it, the verify counts are the source)
def dataset_counts():
    def prefixes(route):
        return [p["Prefix"] for pg in s3().get_paginator("list_objects_v2").paginate(Bucket=B, Prefix=f"{R}/dataset/main/{route}/", Delimiter="/") for p in pg.get("CommonPrefixes", [])]
    p3, p2 = prefixes("3d"), prefixes("2d")
    pjs = pmap(lambda pre: getj(pre + "project.json") or {}, p3, 64)
    c = collections.Counter()
    for pj in pjs:
        k = int((pj.get("slots") or {}).get("model_step") or 0); bs = pj.get("model_step_by_source") or {}
        c["total"] += k
        if bs:
            for src, v in bs.items(): c[src] += v
        else: c["native"] += k            # never touched by a conversion pass: only archive STEP
    return dict(projects_3d=len(p3), projects_2d=len(p2), both=len({x.split("/")[-2] for x in p3} & {x.split("/")[-2] for x in p2}), step=dict(c))
DS = None if vc.get("projects_3d") else dataset_counts()
if DS: print("dataset (project.json):", DS)

# ---------------------------------------------------------------- fleet inventory (counts only)
def fleet_check():
    try:
        roles = collections.Counter()
        for region in ("ap-south-1", "ap-south-2"):
            ec2 = SESS.client("ec2", region_name=region)
            for pg in ec2.get_paginator("describe_instances").paginate(Filters=[{"Name": "instance-state-name", "Values": ["pending", "running"]}]):
                for rv in pg["Reservations"]:
                    for inst in rv["Instances"]:
                        name = next((t["Value"] for t in inst.get("Tags", []) if t["Key"] == "Name"), "")
                        if name in ("cad-disk-extract-hyd-status", "cad-disk-extract-hyd-medium"): roles["support"] += 1
                        elif name.startswith("cad-disk-extract-"): roles["extraction"] += 1
                        elif name.startswith(("cad-db1-", "cad-ifc")): roles["conversion"] += 1
                        elif name.startswith("cad-pkg"): roles["packaging"] += 1
        return dict(checked_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), extraction_vms_running=roles["extraction"],
                    conversion_vms_running=roles["conversion"], packaging_vms_running=roles["packaging"], support_vms_running=roles["support"])
    except Exception as e:
        print("fleet check unavailable:", type(e).__name__, str(e)[:120]); return None
FLEET = fleet_check(); print("fleet", FLEET)

# ---------------------------------------------------------------- public aggregates (no names, no paths)
nat = vc.get("step_source_native", 0); fi = vc.get("step_source_ifc", 0); fd = vc.get("step_source_db1", 0)
pub = dict(schema="cad-step-conversions/v2", generated_at=summary["generated_at"], final=FINAL,
    step_in_dataset=dict(total=vc.get("step_rows_3d", 0) if not DS else DS["step"].get("total", 0),
                         native=nat if not DS else DS["step"].get("total", 0) - pk["step_v1_ifc"]["step_files_added"] - pk["step_v1_ifc2"]["step_files_added"] - pk["step_v1_db1"]["step_files_added"] - pk["step_v1_db1_posthoc"]["step_files_added"] - pk["step_v1_db1_posthoc2"]["step_files_added"],
                         from_ifc=fi if not DS else pk["step_v1_ifc"]["step_files_added"] + pk["step_v1_ifc2"]["step_files_added"],
                         from_db1=fd if not DS else pk["step_v1_db1"]["step_files_added"] + pk["step_v1_db1_posthoc"]["step_files_added"] + pk["step_v1_db1_posthoc2"]["step_files_added"], untagged=vc.get("step_source_MISSING", 0),
                         source="full verification" if not DS else "project.json slot totals and applied packaging plans (before the final verification)",
                         distinct_converted=dict(from_ifc=len({a["out_key"] for n in ("step_v1_ifc", "step_v1_ifc2") for x in plans[n] for a in (x.get("adds") or [])}),
                                                 from_db1=len({a["out_key"] for n in ("step_v1_db1", "step_v1_db1_posthoc", "step_v1_db1_posthoc2") for x in plans[n] for a in (x.get("adds") or [])}))),
    db1_coverage={k: v for k, v in COV.items() if k != "found_list"},
    packaging=dict(format="projpkg4", layout="dataset/main/{3d,2d}",
                   projects_total=(vc.get("projects_3d", 0) + vc.get("projects_2d", 0) + vc.get("empty_packages", 0)) if not DS else DS["projects_3d"] + DS["projects_2d"],
                   verified_projects=sum((v or {}).get("projects_checked", 0) for v in ver),
                   projects_3d=vc.get("projects_3d", 0) if not DS else DS["projects_3d"], projects_2d=(vc.get("projects_2d", 0) + vc.get("empty_packages", 0)) if not DS else DS["projects_2d"],
                   moved_2d_to_3d=sum(pk[n]["moved_2d_to_3d"] for n in pk),
                   corrections=cleanup, info=dict(empty_packages=vc.get("empty_packages", 0)),
                   dedup=dict(content_duplicate_rows=vc.get("content_duplicate_rows", 0), step_content_duplicate_rows=vc.get("step_content_duplicate_rows", 0),
                              step_same_conversion_twice=vc.get("step_same_conversion_twice", 0), step_duplicates_collapsed=cleanup["step_duplicates_collapsed"],
                              rule="inside each project a (channel, ETag, size) content is stored once; each conversion output is placed once per project"),
                   checks={k: vc.get(k, 0) for k in ("step_in_2d", "3d_without_step", "project_in_both_routes", "duplicate_relpath_rows", "rows_without_object",
                                                      "projects_with_content_duplicates", "projects_with_conversion_placed_twice",
                                                      "objects_without_row", "slots_model_step_mismatch", "step_row_without_source", "converted_from_missing",
                                                      "bytes_mismatch", "project_json_route_mismatch", "manifest_unreadable", "project_json_unreadable")}),
    ifc_to_step=dict(distinct_sources=len(ij), converted=ifc_st.get("ok", 0),
                     not_converted=dict(ifc_reason),
                     recovered_by_input_fix=sum(1 for r in ifc_ok if r.get("input_fix") or r.get("input_unzipped") or r.get("repair")),
                     elements_excluded_total=sum(len(r.get("excluded_elements") or []) for r in ifc_ok),
                     converter="ifc2step5.py --mode hybrid --prec 2 (ifcopenshell 0.8.4 for finishing runs)"),
    db1_to_step=dict(distinct_sources=len(jobs), converted=db1_st.get("ok", 0), parts_written=parts_written,
                     elements_excluded_total=sum(len(r.get("excluded_elements") or []) for r in ok_recs),
                     regenerated_outputs=sum(1 for r in ok_recs if r.get("regenerated")),
                     not_converted={DB1_REASON.get(k, (k,))[0]: v for k, v in db1_st.items() if k != "ok"},
                     by_version={v: dict(files=c.get("files", 0), converted=c.get("converted", 0), not_converted=c.get("not_converted", 0)) for v, c in sorted(byv.items())},
                     checks=("Written only when the decoded model passes its checks: member axes agree with their reference lines (>=90% "
                             "per file, parts off by >15 deg dropped), parts named COLUMN are vertical, profile sizes plausible; every STEP "
                             "is AP214 faceted B-rep (flavour-checked) and read back with OpenCASCADE when under 64 MB.")),
    leftovers=dict(extraction=ext))
if FLEET: pub["fleet"] = FLEET
json.dump(pub, open(os.path.join(OUT, "conversions.json"), "w"), indent=1)
print(json.dumps({k: summary[k] for k in ("db1", "ifc")}, indent=1)[:3000])
print(json.dumps(pub["step_in_dataset"]), json.dumps(pub["packaging"])[:800])
