"""Write out/extra.json (notes, repairs, corrections, machines) for make_report_html.py from out/summary.json and the
operator-pass records in S3. Run after build_final.py.  READ-ONLY against S3 (bim)."""
import json, os
import boto3

HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, "out")
S = json.load(open(os.path.join(OUT, "summary.json")))
B = "annotationprod"; R = "cad-disk-extract"; PH = f"{R}/_control/packaging/step_v1_db1_posthoc"
s3 = boto3.Session(profile_name=os.environ.get("AWS_PROFILE", "bim")).client("s3", region_name="ap-south-1")
def getj(k):
    try: return json.loads(s3.get_object(Bucket=B, Key=k)["Body"].read())
    except Exception: return None
def n(v): return f"{int(v):,}"

d = S["db1"]; cov = S.get("db1_coverage") or {}; cl = S["packaging"].get("cleanup") or {}; vc = S["packaging"]["verify"]
ph = json.load(open(os.path.join(OUT, "posthoc_counts.json")))
r865 = getj(f"{R}/_state/db1-v2/results/865f3309e5d4b6e2bd93e1244094d596abecc4f429b2b8419133ff34f6e14ce6.json") or {}
regen = [x for x in (getj(f"{PH}/fix/{s}.summary.json") for s in ("b5e0694a4b02a8ecced6c4128b00d8a941e23756574f6a8959a45bc178df7d1e",
                                                                  "9c2e39cb0fcfc14665403bc76e27aba7c3a17e7578f1c5c448824856d8dadda2")) if x]
base = json.load(open(os.path.join(HERE, "extra_draft.json")))
repairs = list(base.get("repairs", []))
repairs.insert(1, "<strong>Tekla arc points in plate outlines.</strong> Tekla marks outline corners as arc points (a round plate is a square "
               "whose four corners are all arc points). The first writer drew one arc per point, so neighbouring arcs overlapped into "
               "self-crossing outlines. Each edge that touches an arc point is now one arc through that point and its neighbours; "
               "roundings that overlap on one edge are shrunk in proportion. Every earlier output with contour plates was re-decoded "
               "and rewritten only where an outline actually changed.")
if r865.get("status") == "ok" and r865.get("excluded_elements"):
    ex = r865["excluded_elements"]
    repairs.append(f"<strong>One DB1 model hung the geometry kernel.</strong> A {int((r865.get('convert') or {}).get('written') or 0):,}-part "
                   f"Tekla 8.07 model stalled at the same element on every run. Bisection found {len(ex)} element "
                   f"({', '.join(e.get('name') or e.get('type') for e in ex)}, a cut beam). It was left out and listed, and the other parts converted.")
if regen:
    repairs.append("<strong>Vertices at the geometry kernel's infinity.</strong> Two DB1-derived STEP files (" +
                   " and ".join(f"{n(x['parts'])} parts" for x in regen) + ") each held a mesh vertex at OpenCASCADE's infinite bound "
                   "(2&times;10<sup>100</sup> m). Re-tessellating the same decoded model gives none, so both files were regenerated and "
                   "checked: same parts, no such vertex, and a normal extent. Every other output's recorded extent was checked for "
                   "the same fault (none), and the 67 largest IFC outputs, which have no recorded extent, were scanned point by point.")
corrections = [
    f"<strong>{n(cov.get('found_never_attempted', 0))} Tekla model files no converter had attempted</strong> were found by matching every "
    f"DB1 in the dataset against every conversion attempt. They sat mostly inside nested zips or in archives extracted after the "
    f"original converter took its file list. All were converted in this run. One more file that the original pipeline left "
    f"'unknown' (an 827-byte Tekla 6.87 stub) was decoded: it has no part table.",
    f"<strong>{n(ph['packaged_identity_matches'])} packaged copies of already-converted DB1 files had no STEP placed.</strong> Each is "
    f"byte-identical to a converted file, but its source object was uploaded with a different multipart layout, so its S3 "
    f"ETag differed and the first placement pass did not match it. These are now matched by the packaged object's own "
    f"content identity. Together with the new files, {n(ph['step_files_placed'])} STEP files were placed in {n(ph['projects'])} "
    f"projects, and {n(ph['moved_2d_to_3d'])} of those projects moved from 2d to 3d.",
    f"<strong>{n(cl.get('empty_step_removed', 0))} header-only STEP files removed from {n(cl.get('projects_with_empty_step', 0))} projects.</strong> "
    f"The original DB1 pipeline wrote a STEP containing no geometry (one product with an empty shape) for every file it failed on, and the "
    f"first packager copied those in as models. Each project records what was removed. No project lost its last real STEP.",
    f"<strong>{n(cl.get('step_duplicates_collapsed', 0))} byte-identical STEP files collapsed in {n(cl.get('projects_deduplicated', 0))} projects.</strong> "
    f"Different sources, such as two dated IFC exports of the same model, had produced identical STEP. One file is kept, and its manifest row "
    f"lists the other sources (<code>also_converted_from</code>), so every source still points to a STEP.",
    "<strong>Empty test package removed.</strong> <code>Disk-1___probe</code> (the extraction pipeline's probe run, 0 files) is no longer in "
    f"the dataset. {n(max(0, (vc.get('empty_packages') or 0)))} real archives held only non-asset files, so their packages hold only project.json. They are kept "
    "and marked as empty packages.",
    "<strong>Packaged copies refreshed.</strong> Every placement was checked against its conversion output. Copies of outputs repaired after "
    "packaging (11 IFC, 2 regenerated DB1) were re-copied, with their manifest rows and project totals updated.",
    f"<strong>Tekla component libraries.</strong> {n(cov.get('xslib_library_distinct', 0))} distinct <code>xslib.db1</code> files are Tekla's "
    "per-model libraries of custom components, not the building model, so they are not converted. The original pipeline skipped them too. "
    "Seven xslib-named files had been in the original scope and were converted. Two of them are building-scale models (about 2,600 "
    "members each) saved under that name, and all seven passed the same checks as any model.",
    "<strong>Known real outlier.</strong> All 50 versions of one model (30558 Bend Surgical) contain one W16X40 beam about 100 km from the "
    "rest of the model. It is decoded as a well-formed part with a sane profile, length and orientation, so it is the model's own content "
    "and was kept as modelled.",
]
teton = [getj(f"{R}/_state/db1-v2/results/{s}.json") or {} for s in ("a3200ff3949dfe7883c45d9aee386a522b00997b43e441dcfb0be6a1d464838f",
                                                                      "f8f6249901b56fb32663e3c1d6eb7f4aa4a0146271166ade14c280d9e9cb826c")]
if teton:
    ok_t = [t for t in teton if t.get("status") == "ok"]
    exc = sum(len(t.get("excluded_elements") or []) for t in ok_t)
    corrections.append("<strong>Two re-runs interrupted, then finished.</strong> Two versions of one model (Teton Village H1) were still "
                       "being rewritten for the arc-point fix when idle machines were shut down, and the shutdown stopped them. Both "
                       f"were re-run on the last machine: {len(ok_t)} of 2 converted"
                       + (f", leaving out {exc} element(s) that hang the geometry kernel (listed in their results)" if exc else "")
                       + ", and their packaged copies were refreshed.")
fleet = [
    "DB1 fleet (13 &times; r7i.16xlarge, Mumbai + Hyderabad) and the research box: 10 idle boxes were terminated once every job was final. "
    "The last box finished the checks above and shut itself down.",
    "Packaging boxes (Mumbai, Hyderabad): shut themselves down after the end-game (all markers written, 22:15 UTC).",
    "Old Windows converter box (c7i.24xlarge, idle since Sep 24): terminated with approval.",
    "Not touched: the extraction status boxes (cad-disk-extract-hyd-status, cad-disk-extract-hyd-medium).",
]
notes = [f"Every conversion job is final: DB1 {n(d['outcomes'].get('ok', 0))} of {n(d['distinct_files'])} converted, "
         f"IFC {n(S['ifc']['outcomes'].get('ok', 0))} of {n(S['ifc']['distinct_files'])}. The full structure check "
         f"ran on all {n(vc.get('projects_3d', 0) + vc.get('projects_2d', 0) + vc.get('empty_packages', 0))} packages after the last change."]
json.dump(dict(notes=notes, repairs=repairs, corrections=corrections, fleet=fleet), open(os.path.join(OUT, "extra.json"), "w"), indent=1)
print("extra.json written:", len(repairs), "repairs,", len(corrections), "corrections")
