# Non-IFC track: DB1-sourced perfect-tier models (bench `nonifc_db1`)

Bench: i-0a8e721cc7429893e (ap-south-2), work dir `/opt/bench/nonifc_db1`. Nothing ran on the Mac except S3 listings / reads
of small objects (kit version history, heads). S3 writes: only `bench.sh pull` (-> `_state/pm_samples/bench/nonifc_db1/out/`).

Scope: 174 perfect-tier rows with `step_source = db1` (report_v1/data/projects_f1.json) = **171 distinct models** (3 models
sit in two packages each: b56ad5e78f4a, b5b316b97313, dd7652240949; the jobs file has one entry per model id, the other
package in `also_pids`).

Result in one line: **171 / 171 IFCs regenerated and proven to reproduce the shipped STEP byte for byte** (apart from the
write time in FILE_NAME and ifc2step6's thread-order entity numbering), GlobalIds restored, published; **0 excluded**.
Pipeline (perfect flags) per model: see the table at the end.

## 1. Pinning the producing kit per model (u / v / "q")

Evidence used, per model (`db1_regen/regen_inputs.json`):

* package STEP vs `conversions/db1-step/<sha>.u.stp` (head-object: ETag, size, LastModified) and the conversion result
  JSON (`_state/conv2/db1/results/<sha>.json`: code, started/finished). NB: the worker's output suffix `VSUF` stayed
  `.u` in code v, so `.u.stp` is NOT "code u": the 2026-10-06 code-v re-run overwrote `.u.stp`, and the
  `converter.code` in projects_f1.json (u for 136) is stale (packaging recorded it before the v re-run).
* **The DB1 kit is fully recoverable from S3 object version history** (`annotationprod/.../_control/z3conv/db1/` is a
  versioned bucket). `db1_regen/scripts/kit_snapshot.py <time>` rebuilds the kit as it was live at any time;
  manifests (file, VersionId, md5) in `db1_regen/kit_manifests/`.

| kit | models | evidence |
|---|---|---|
| kit_v = `z3-db1-2026-10-01v` | 160 | package STEP == current `.u.stp` (same ETag, or same size + multipart ETag and packaged after the 2026-10-06 v run); kit = S3 snapshot as of 2026-10-06T00:00Z (v re-run started 00:05Z), byte-equal to the live kit |
| kit_u = `z3-db1-2026-10-01u` | 10 (all 6.87 / 7.01) | packaged 2026-10-04 22:12Z .. 10-05 03:24Z, size differs from the v re-run's `.u.stp`; kit = S3 snapshot as of 2026-10-05T20:00Z (CODE u), byte-equal to live kit + `z3conv/_sprint/db1-code-v/u/` (5 files) |
| kit_u | 1: **97c7c25d3237 (DoingSTD, data-3)** | the previous note said "code q, kit lost - exclude". Wrong on both counts: the shipped STEP's own header is `FILE_NAME(...,'2026-10-02T21:45:54',...,'ifc2step6 6.1.7',...)`; the kit live at that time (S3 snapshot, worker CODE u) has every decoder / STEP-stage file byte-equal to kit_u. The `.q.stp` merely has the same size (FILE_NAME 08:25:44 / 6.1.5). The q kit (snapshot 2026-10-02T08:25:44Z) reproduces the same geometry too (u and q identical for this model); pinned to u because the shipped FILE_NAME names 6.1.7 |

## 2. Regeneration (on the bench, separate env `/opt/bench/nonifc_db1/conv`)

Env = production `z3conv/db1/setup.sh` spec: conda env python 3.11.17, ifcopenshell 0.9.0, **pythonocc-core 8.0.1**
(production printed `occ 8.0.1`; 8.0.1.1 was replaced by the exact pin), shapely 2.1.2, numpy 2.4.6; venv `ifc84`:
ifcopenshell **0.8.4.post1** (decoder IFC writer + STEP stage, as in production). micromamba from micro.mamba.pm
(conda-forge), pip from PyPI. `/opt/pm/venv` untouched; nothing in `/opt/pm/jobs` touched.

`db1_regen/scripts/regen.py JOBS MID KIT` per model, exactly the worker's `process()` chain:
1. packaged DB1 (`model/db1/...`) -> sha256 must equal the model id (171/171 do);
2. `convert_one.py in.db1 model.ifc tekla_profiles.json layout.json convert.json variants.json` (ifc84 python, layout of
   the file's engine from the kit's layouts.json, all approved variants, `DB1_FULL_DISCOVERY=1` retry on
   deferred_layout - as worker.py) -> model.ifc (catalog overlay md5 0394baae... = the md5 the results record);
3. `ifc2step6.py model.ifc model.stp --mode hybrid --prec 2 --threads 4` (ifc84 python; OCC read-back verifier = env);
4. `stepcmp.py` regenerated vs shipped STEP: every line byte-equal after replacing each `#n` by the line number that
   defines it (ifc2step6 numbers entities in worker-thread completion order: the same lines in the same order get
   different numbers run to run), FILE_NAME (write time) not compared, PRODUCT.id (= IFC GlobalId, random per decoder
   run) aligned -> regenerated->shipped GlobalId map (bijection, same line = same part);
5. GlobalId restore = text substitution on the IfcRoot entity lines only (no re-serialisation): product GlobalIds from
   the map; IfcRoot entities without a STEP product (IfcProject, IfcSite, IfcRelAggregates, IfcRelContainedIn..., 4 per
   model) get `ifcopenshell.guid.compress(sha256("<model id>:<entity id>")[:32])` - not recoverable from the STEP,
   deterministic. FILE_NAME time and IfcOwnerHistory.CreationDate are the regeneration time (not the original);
6. the restored IFC converted again with the same kit: **its STEP equals the shipped STEP byte for byte, every
   PRODUCT.id included** (FILE_NAME line and entity numbering excepted) -> verdict `reproduced`, IFC -> `ifc/<id>.ifc`;
7. cross-check vs the conversion fleet's own census of ITS IFC (`detail/<sha>.u.src_parts.jsonl.gz`: gid, class, name
   per product with a body): available for the 160 kit_v models (the census belongs to the v run) -> 160/160 all match
   (same GlobalId set, class and name for every product).

Results: `res/<kit>/<id>.json` on the bench (pulled copy in the jobs file's provenance). 171 / 171 reproduced
(160 v + 11 u), 0 mismatches, 0 failures. Largest: d869ee841d83 (6.87, 14,489 parts, shipped STEP 1.0 GB).

Published: `s3://bim-proprietary-data/cad-disk-extract/_state/pm_samples/bench/nonifc_db1/out/ifc/<model id>.ifc`
(171 files; sha256 per file in the jobs file `source_ifc_sha256`, checked against the S3 objects on the bench).

## 3. Independence (README must say this)

The IFC is OUR decoder's intermediate (db1step, IFC2X3), regenerated with the kit that wrote the shipped STEP. The
pipeline's source check against it is therefore a consistency check (decoder IFC -> IfcOpenShell kernel vs our build123d
rebuild), not an independent reference; the delivered STEP was written by IfcOpenShell from the same IFC.
`source_kind = regenerated_from_db1` in every job.

## 4. Pipeline code changes (code copy `full/nonifc/code_db1`, base = code_v9a)

Profile types in the 171 regenerated IFCs (`scan_profiles.py`): ArbitraryClosed, Rectangle, IShape, Circle, LShape,
RectangleHollow, CircleHollow, UShape, **TShape (93 defs, 34 models)**, RoundedRectangle (16 defs, 10 models = the u-kit
slots). No C, Z, asymmetric I, no half spaces, no revolved solids. extract/steelbuild lacked only T.

1. **IfcTShapeProfileDef** (`tools/extract.py` Profiles.describe, `kit/steelbuild.py` profile_face kind `T`): d, b, tw,
   tf, r = FilletRadius, r_edge = FlangeEdgeRadius (existing columns; no new column). WebEdgeRadius / slopes ->
   Unsupported as before (exact path; none in our data). Geometry probed on the IfcOpenShell 0.9 kernel
   (`probe_profiles.py`, IFC2X3 and IFC4): flange on top, web centred, root fillets tangent to web and flange underside,
   flange-edge radius on the flange-toe undersides. `test_tprofile.py`: area equal to the kernel's to 1e-15 relative and
   every outline edge equal (3 variants incl. fillet + flange edge radius).
2. **Kernel-unbuildable cut tools** (`steelbuild.kernel_unbuilt`, used in build_solid's kernel rules and for openings in
   build_part; `tools/reference_defects.py` lists such parts as `kernel_unbuilt_tool_parts`, key written only when
   present). The u-kit slots are IfcRoundedRectangleProfileDef with RoundingRadius = XDim/2 (full-round slot). Measured
   on IfcOpenShell 0.9 (`probe_rrect.py`): radius >= half the smaller side - 5e-5 mm -> GEO027 'Unknown error creating
   geometry', the solid is left out (a cut tool removes nothing); radius = half - 1e-4 mm builds (OCC confusion 1e-7 m
   in the kernel's metre units). Both references keep that material (source = 0.9 kernel; delivered = 0.8.4 kernel:
   delivered volume within 0.08 % of source, rebuild with slots cut 0.6 % below). Before: canary 54342bbc6571 3 parts
   MISMATCH (source DIFFERS, kernel log GEO027 on the 4 slot extrusions); after: 78/78 match, parts listed in
   reference_defects_summary.json as agreeing with the kernel, not with the cut the IFC states. Same convention as the
   existing GEO154 rule (build_solid keeps the first operand where the kernel gives up). No geometry is invented: the
   rebuild omits a cut that neither reference has.

Regression proof (`benchkit/regression.json`, 36 models, bench run_local):
* final code vs code_v9a control run: **36/36 IDENTICAL** (16 schedule / script-input files byte for byte + verdict
  fields) - `cmp_runs.py reg_v9a reg_db1b`;
* final code vs the fleet's outputs on S3 (`benchkit/compare.py reg_db1b`): **36/36 unchanged**; control vs fleet 36/36.
* Honest scope of "no IFC-sourced change": the two changes only act where an IFC holds an IfcTShapeProfileDef or a
  full-round IfcRoundedRectangleProfileDef cut / opening tool. Scan of the 7,730 IFC-sourced models the fleet had
  finished (`scan_fleet.py`, their extract_info / profiles / solids): **92 models hold T parts (4,560 parts, today exact
  from the delivered faces) - they WOULD change** (T parts become parametric) if this code ran on them; 0 hold a
  full-round rounded-rectangle tool. T-impact sample (8 smallest of the 92, final code vs v9a control): see section 6.
  So: use this code copy for the non-IFC jobs; merging it into the IFC fleet needs those 92 re-run.

## 5. Jobs file

`full/nonifc/nonifc_db1_jobs.json`: one entry per model {id, pid, step, ifc `<id>.ifc`, ifc_key
`cad-disk-extract/_state/pm_samples/bench/nonifc_db1/out/ifc/<id>.ifc`, bytes, cls (1e7/1e8/5e8/1e9 decimal, as the
fleet), tool 'db1', gen 1, source_kind 'regenerated_from_db1', also_pids, source_ifc_sha256, provenance {db1 key / sha /
engine, kit code + S3 snapshot time + VersionIds / md5 of the decoder and STEP-stage files, env, shipped STEP key / sha256 /
FILE_NAME, proof numbers (lines, products, diff_lines 0), census check, GUID rule, kit pin evidence}}.

## 6. T-impact sample on IFC-sourced models (not part of this track's output; evidence for a later merge)

8 smallest of the 92 IFC-sourced models with T parts, bench run_local, final code vs code_v9a control (same box):
schedule files differ in all 8 (expected: T parts now parametric), perfect flags: 5f09151ab215 T->T, 349fb8c54bfa T->T,
8adda974b938 T->T, **dded88685ec5 F->T** (3 recovered T parts MISMATCH before, now parametric match), d9dde1b788ac F->F,
c62967b95abd F->F (levels), c8f831d171ae F->F (levels), 8aadc5b78b6e F->F (SDS/2 IFC whose delivered STEP lacks the parts:
no_delivered_part 75 -> 81, BUILD_ERROR 8 -> 2). 0 regressions, 1 model gained. The fleet's own v9a verdicts for these 8
equal the control's.

## 7. Bench runs (all under /opt/bench/nonifc_db1)

| what | run dir | code |
|---|---|---|
| regeneration + proof, 171 models (+ 97c7 with kit_q) | work/, res/, ifc/, shipped/ | kit_v / kit_u / kit_q |
| pipeline canary (5) before the slot rule | pipe_canary | code_db1 (T only) |
| canary 54342bbc6571 after the slot rule | pipe_canary_b | code_db1b (final) |
| regression 36: T-only / control / final | reg_db1 / reg_v9a / reg_db1b | |
| T impact sample 8 | regT_db1b / regT_v9a | final / v9a |
| full pipeline, 171 models | pipe_full (+ pipe_full_b: the 70 smallest run a second time in parallel) | code_db1b = this copy |
