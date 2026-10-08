---
name: project-parametric-samples
description: "Parametric build123d scripts + classified inputs for 5 Disk-1 perfect sample projects (2026-10-06): method, locations, results, gotchas"
metadata:
  node_type: memory
  type: project
  originSessionId: f63cb79e-c4e0-4f10-ab61-521e6153b162
  modified: 2026-10-07T07:12:17.358Z
---

Client asked for executable parametric construction scripts (build123d), headless reproduction, drawing match, inputs.
Owner chose 5 Disk-1 perfect projects with INPUTS/UPLOADS/COMMENTS-style folders: Giorgi USA 19058 (25 models), Cook
Children's Walsh Ranch, Pinewood Prep, Guthrie Buildings (4 models), CMC Texas (2 models) = 33 delivered models, 42,199 parts.

**Method (decided by me, owner delegated):** source = each delivered STEP's IFC -> schedules (profiles/solids/cuts/openings,
parts with marks) -> build123d `steelbuild.py` + per-model `build_model.py` (whole model / `--assembly` / `--mark`).
NC1 only as cross-check (teammate's NC1->piece-script POC cannot place pieces; Giorgi/Guthrie have no NC1).
Faceted-only parts: `recovered` (verified straight extrusions) or `exact` (faces). Verified per part vs IfcOpenShell exact
B-rep (SERIALIZED, separate process: ifcopenshell + OCP in one process segfaults) and vs delivered faceted STEP.

**Kernel conventions that had to be matched:** booleans around a part-local origin (models 400 m from origin lose cuts);
fuzzy cuts 1e-3 mm (coincident faces leave laminae); sloped U flanges = tf on centre line tapering to toe; edge radius
larger than toe -> straight chamfer walked along outline; Revit profile gaps; stepfacets centroid relative to local origin.

**Where:** toolkit `~/Downloads/Deccan/z3conv/parametric/` (tools/, kit/, samples/stage.py, drawcheck/, nc1check/,
inputs/_tools). Cloud run on coordinator `/opt/pm` (venv build123d 0.13 + ifcopenshell 0.9; `tools/cloud_pipeline.sh`),
results `s3://bim-proprietary-data/cad-disk-extract/_state/pm_samples/`. Sample packages:
`s3://bim-proprietary-data/cad-disk-extract/dataset/samples/parametric_v1/<project_id>/` = projpkg4 copy + inputs/ +
scripts/ + verification/ + SAMPLE_README.md + sample_manifest.jsonl.

**Findings:** Pinewood NC1 461/471 join, profile/grade 100%, length 98.5%; Pinewood drawings 4,616/4,675 sheets match by mark.
Giorgi Tekla + 3 Guthrie models are unnumbered ("(?)" marks); Revit/HiCAD have no marks; CMC Model1 is a different job.
Inputs: 118,466 archive files located; PII (payslips, ID copies, CVs) excluded.

**NC1+KISS+BOM+IFC ("Gemini recipe" the teammate forwarded 2026-10-06):** only Pinewood has all four describing the
delivered model. Giorgi/Guthrie: no NC1/KISS. Cook Children's (1,005 NC1, 11 kss) and CMC Texas (1,232 NC1, 91 kss) are
the fabricator's Tekla model while the delivered STEP is the client's Revit design model (0 / 21 NC1 join). NC1 has no
placement and covers only CNC pieces; KISS = D lines (assy mark, rev, main, piece mark, qty, shape, size, grade, length mm,
finish, remark; bolts = shape MB, blank piece mark), L lines (Holes/Weld/Cuts counts), A, S lines -> checksum only.

**Parametric gap (v1):** 9,922 of 42,199 parts exact (giorgi HiCAD 5,846 because recover crashed in v1; anchors ANKER =
octagon swept along a bent path; welds 1,302; Pinewood "Support section" 858). Workflow `parametric-coverage`
(wf_ce120f00-204, scratchpad cov/) builds sweep / cut-tool recovery, crash fixes, KISS checksum.

**State 2026-10-06 22:45 PDT:** v7 published (42,176/42,199 parts, 28/33 models perfect, 0 regressions vs v6).
v8 AUTOPILOT armed on coordinator (/opt/pm/ap8/run.sh; log s3 .../_state/pm_samples/autopilot/autopilot.log, gate.json):
9 workers (5 Mumbai + 4 Hyderabad, tags cad-pm-samples-v8b0..8, userdata_pm_v8auto.sh, code autopilot/code_v8auto.tgz =
sweep + cut-tool recovery + STEP-export vertex snap) -> out_v8; publishes ONLY if 0 regressions vs v7 + 33/33 deterministic.
Gate on 8 models already: 2,941 exact->parametric, 0 regressions. Open: ifcfaces (16 purlins + CMC slab: build exact faces
from IFC full precision, not delivered STEP) and residual (2 CMC bolts, Pinewood weld + 3) - cloud-fixes workflow,
benches cad-pm-bench-{ifcfaces,residual,sweepcut} (6 h self-shutdown); helper /tmp/z3c/bench.sh (Mac writes annotationprod
coord_tmp, boxes write bim-proprietary-data). Mac SSO role cannot PutObject to bim-proprietary-data.

**2026-10-07 00:10 PDT:** v8 autopilot FAILED safely (sweep/cut recovery hangs: GRID_10 workers 60 GB / 68 min) -> stopped,
v7 still live. Ankit (akhdec) audit: github deccanai-org/cad-dataset-packager issue #7 (6 findings + CMC bolt re-sew patch),
PR #8 FINDINGS.md, readiness review (copies in scratchpad ankit/). Workflow full-fix-v8 (wf_0dd84115-d40) streams recover /
ifcfaces / residual / verifycov / claims on benches cad-pm-bench-{sweepcut,recover2,ifcfaces,residual,verifycov,claims}, then
critic; I merge -> fleet run -> gate vs v7 -> publish to the same 5 package links. SSO expires overnight: re-login with
`aws sso login --profile annotationprod-publish --use-device-code --no-browser`, user approves the URL.

**Determinism gotcha:** build_model output was not byte-identical across --jobs (tolerance lines + pcurve points at
1e-6) because extrude_solid's cached profile face shares TShapes and booleans raise their tolerances in place. Fix = copy
the cached face per solid (BRepBuilderAPI_Copy).

Related: [[project-zenitude-report]], [[project_cad_packaged_dataset]]

**v9 PUBLISHED 2026-10-07 10:27 PDT** (same 5 package links): 42,195/42,199 parts match, 20 fixed, 0 regressed, 4 left
(2 reference_defect, 2 undetermined), source-checked 42,157 (was 29,238), exact parts 613 (was 4,702), models ok 31/33,
e2e 33/33, determinism 33/33, all README commands pass; READMEs computed from package files (19 distinct models).
Code: scratchpad mv9/mergecode/final (code_v9.tgz), staging mv9/mergedocs/final (stage_v9.tgz); gate /opt/pm/ap9 on coord.
PENDING OWNER OK: delete 17 stale v7 files no longer shipped (giorgi 7, cook 7 under verification/drawings_vs_model +
nc1_vs_model; guthrie 3 under nc1_vs_model). GitHub reply draft: z3conv/parametric/REPLY_issue7_draft.md (not posted).
Perfect-tier estimate given to Dhiren: 12,467 IFC-sourced class-1 STEP -> ~11,478 distinct by size -> ~8-9k distinct
models (sample ratio 19/27); DB1 174 + SDS2 97 need new extractors. Exact count needs extract+fingerprint pass.
Mumbai vCPU quota (2000) was saturated by another team's RL-Blender m7i fleet on 10-07; Hyderabad used instead.

**metadata.json added 2026-10-07** to all 5 packages (generator /tmp/z3c/gen_metadata.py, backup z3conv/tools/z3c_backup; runs on coordinator over /opt/pm/ap9/samples/stage): ids/units/schedules/materials/project/provenance/license(blank)/engineering_design_rationale; tonnage per model only (HiCAD giorgi models hold ~93 t "SLAB" members with steel grade; giorgi files are versions of one job).
