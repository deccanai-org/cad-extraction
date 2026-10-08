---
name: project-pmx-full-corpus
description: "Full-corpus parametric run (pmx, started 2026-10-07 15:20 PDT): 12,467 IFC-sourced perfect-tier models on a ~2,700 vCPU fleet; S3 layout, control, scheduler, fix rounds"
metadata:
  node_type: memory
  type: project
  originSessionId: f63cb79e-c4e0-4f10-ab61-521e6153b162
  modified: 2026-10-07T22:40:00.509Z
---

Dhiren asked (2026-10-07 afternoon) to scale the v9 headless parametric build123d pipeline from the 33 samples to ALL
perfect-tier class-1 models, "fully perfect", asap, as many instances as possible (Mumbai up to 1400 vCPU if free).

**Inventory:** report_v1/data/projects_f1.json steps[] class 1 = 12,738 rows: ifc 12,467 distinct model_id (= IFC sha256),
db1 174, sds2 97. Tools (ifc_headers.json): tekla 8,147, sds2 2,789, blank 1,114, other ~400. Sizes: S<10MB 7,854,
M<100MB 2,880, L<500MB 1,381, XL<1GB 218, XXL>=1GB 134 (tail = 42% of the 1.02 TB of STEP; max 14 GB).
DB1/SDS2 (271) need a separate track (agent report 10-07: DB1 IFC is regenerable from z3conv/db1 kit, never uploaded;
SDS/2 needs an IFC emitter; ~17-27 engineer-days; source would be our own output -> not independent).

**Fleet code:** scratchpad full/fleet/ (worker.py, job.py, userdata.sh, launch.sh [SPOT=1], launch_bench.sh, status.py,
triage.py, benchkit/{run_local.py, compare.py, regression.json}). Control (Mac writes): s3://annotationprod/
cad-disk-extract/_control/z3conv/coord_tmp/pm/full/ {control.json, jobs_v1.jsonl.gz, worker.py, job.py, code_<ver>.tgz,
requirements.txt (pinned freeze of the v9 venv)}. State (boxes write): s3://bim-proprietary-data/cad-disk-extract/_state/
pm_full/ {claims/<id>.g<gen> (S3 conditional PUT If-None-Match / If-Match takeover after 15 min no heartbeat), hb/, done/
<id>.g<gen>.json (summary + perfect flag + reasons), retry/ (memguard class bump), boxes/<iid>.json, out/<id>/, logs/}.
Rerun a model = bump its gen in a new jobs file; a job may pin "code": "<ver>". control: hold, hold_boxes (box -> bench), idle_min.
Scheduler: classes S/M/L/XL/XXL/XXXL -> J 4/8/16/32/56-96; admission on measured CPU (<85%), 3x NCPU J cap, memory
headroom, reservation for the box's top job (no starvation of big jobs); boxes "asc" (small first) / "desc" (big first);
big box r7i.48xlarge takes L+ only. Hot reload: worker re-execs on worker.py change and adopts running jobs.

**Capacity found 10-07:** on-demand quota Mumbai 2000 (RL-Blender + others use ~1,775 -> only ~2 boxes for us),
Hyderabad 1500, Singapore 320; every other region denies RunInstances. SPOT has a separate 256 vCPU quota per region
(works). Fleet: 21 std r7i.16xlarge + 1 r7i.48xlarge Hyderabad, 5 Singapore, 2 Mumbai, + 12 spot (m7i/r7i.16xlarge).
Benches: coordinator i-039e769ea62de0fa1, benchA i-0f35da72bf742063d (Mumbai r7i.8xlarge), benchB i-036856df4c0fcfd95
(Hyd r7i.4xlarge), + held fleet boxes i-0eaaa4ab9c78b6488, i-044e7693566bfebef.

**Code versions:** v9a = v9 + tekla_checks ratios include v_tekla (KeyError crash on ~10% of Tekla models). Fix round 1
(workflow pmx-fix-round: sds2 no_delivered_part, parametric MISMATCH, GlobalId not found -> merge v9b) and round 2
(pmx-fix-round2: e2e failures, exact-geometry failures, misc crashes) running 10-07 ~15:45 PDT. Plan: merge all ->
regression gate (byte-identical on perfect models) + adversarial review -> rerun failing models via gen bump ->
stage (agent building full/stage/stage_full.py, target dataset/parametric_v1/<package_id>/) -> publish.

First results (1,946 done): 80% perfect; SDS/2 S ~64% perfect (no_delivered_part), Tekla S ~81% (tekla_checks crash).

Related: [[project-parametric-samples]], [[feedback-fleet-worker-lessons]], [[feedback-mumbai-vcpu-cap]]

**10-07 ~16:45 PDT update:** staging tool DONE (scratchpad full/stage/stage_full.py + stage_check.py; needs
`--code v9=... --code v9a=...` for mixed versions). Workflows running: pmx-fix-round (r1), pmx-fix-round2, pmx-nonifc
(DB1/SDS2), pmx-perf (e2e read-back is 69% of wall time; serial), pmx-final5-upgrades (exact B-rep distance gate <=0.1 mm
two-sided, pset marks incl. Tekla 2018+ Pset_*Common.Reference, PII redaction of staged outputs) - ideas from Dhiren's
Final5 pipeline (~/Downloads/Final5_PIPELINE.md, code zip unpacked at scratchpad/final5/). Held boxes (benches):
i-0eaaa4ab9c78b6488, i-044e7693566bfebef, i-0a8e721cc7429893e, i-0d3e1ca73ea6876de, i-017d6427d1ba2e850,
i-0fb49cc0f5bf13047, i-06a889d6cd53bdfe4. Biggest failure cluster: Tekla S parametric MISMATCH (~650 models: bbox exact,
vol 0.1-3% / centroid up to 11 mm off -> cut handling; delivered STEP sometimes closer to rebuild than ifcopenshell 0.9).
ETA given 16:30: S/M/L + fixes + reruns ~21-23 PDT; XL/XXL tail ~midnight-2 AM; DB1/SDS2 late night.
Spot box interruptions happen (Singapore 10-07) -> claims taken over; launch.sh SPOT=1 to replace.

**Live page (10-07 18:30 PDT):** https://dhigdec.github.io/cad-extract-status/parametric.html (public repo -> anonymous
numbers only). Publisher on the Mac: z3conv/tools/publish_parametric.py (nohup caffeinate loop, 300 s, log
publish_parametric.log, cache .parametric_done_cache.json); workstream rows from z3conv/tools/parametric_workstreams.json
(edit by hand as tracks change). Pages build errored once on GitHub's side -> `gh api -X POST repos/dhigdec/cad-extract-status/pages/builds`.
Session restart at ~18:10 stopped all workflows -> resumed with resumeFromRunId. Perf v9p (2.9-4.5x, byte-identical) is
packaged (scratchpad full/code_v9p.tgz) but releasing to the fleet control prefix was BLOCKED by the auto-mode classifier
(Modify Shared Resources) -> ask Dhiren before any fleet code/control release.

**Releases go through `bash z3conv/tools/pmx_release.sh FILE...`** (Dhiren added an allow rule 10-07 18:44; validates and
uploads control.json last). v9p live 18:45; worker PSS memory accounting 19:00; jobs_v2.jsonl.gz (177 tekla-crash-only
models gen 2) 19:15 - jobs_v2 is now the BASE jobs file for further edits (local fleet/jobs_v2.jsonl.gz).
Gap analysis 19:10 (3,795 non-perfect of 10,234): exact-face geometry 1,024 only, parametric 956, e2e-only 228, SDS2
delivered 194, tekla crash 178, levels 70, several causes 1,090; median failing parts per non-perfect model = 6.
Live page has a "Where the gap is" section (publisher `causes()`). Extra track pmx-exact-scale on bench i-05d0eeccfafd799ae.

**PUBLISH LOCATION DECIDED (Dhiren 10-07 ~20:15 PDT):** inside each package, SAME LAYOUT AS THE 5 SAMPLES (corrected by Dhiren): dataset/packages/3d/<package_id>/{scripts/,
verification/, metadata.json, <README>, <added-files manifest like sample_manifest.jsonl>}; projpkg4 files (incl. manifest.jsonl)
untouched; no inputs/ in this publish. Publish with v10, only after the PII gate passes review; workflow pmx-publish-samplelayout adapts the stager
(scratchpad full/stage_inpkg/) and checks the perfect-tier packager/finisher won't rewrite manifests. Worker has a
`restart_old_code` control rule ({"codes":[...],"classes":[...]}) - used 20:30 to restart 68 v9a big jobs on v9p.

**GitHub (10-07 22:30):** private https://github.com/deccanai-org/parametric-cad (local ~/Downloads/Deccan/parametric-cad):
pipeline/ (v9p tools+kit), fleet/, stage/{samples,full,inpackage}/, fixes/<track>/ (notes + patch vs v9a), ops/. Data,
client files, kiss, refs pruned; paths via PMX_HOME. Push v10 there when merged. v10 merge workflow pmx-merge-v10 running.
- **Repo sync:** after every milestone run `bash ~/Downloads/Deccan/parametric-cad/ops/sync_repo.sh "msg"` (copies fleet, all fix tracks' full code, non-IFC, staging, v10, non-perfect snapshot; secret scan; push). Owner wants EVERYTHING kept current there; docs/CONTEXT.md must be updated at milestones.

**10-08 ~00:15 PDT (new session 95c3cc32):** v10 live since 23:05 (jobs_v5 = non-perfect reruns + XL/XXL, control order=random).
Perfect 7,666 / 11,694 processed. Owner goal: **11,000 perfect**, fully buildable polished client scripts, any number of
versions. Mumbai cap raised to ~1,350 CAD vCPU (auto top-up loop fleet/topup_mumbai.sh, log ~/.pmx_topup.log). Tracks
running (new session workflows): exact-fix (wf_c0b38196), parametric2b (wf_d919cab7), exactdist2 (wf_237fea44),
perf-harden (wf_6f57203a), v10-residual + kit-polish (wf_098571e5; benches i-0dd060c20450dd5e1, i-02da04b4b1638a818).
Old-session workflow journals can't be resumed from a new session -> relaunch the script fresh. PII: owner said drop it
(round 4 approved, follow-up stopped). Post-v10 failures: parametric MISMATCH 422, exact MISMATCH 189, invalid solids ~150,
levels/e2e ~60, 9 v10 crashes.
**Publishing started 10-08 ~00:30:** wave 1 = 136 all-perfect single-version packages (workflow pmx-publish-wave1: packager orphan patch + staging on box i-0dac69095286d7a6f + RUNBOOK at scratchpad full/publish/); jobs_v6 reruns 6,021 models of 161 mixed-version packages onto v10. Owner treated 'should be publishing' as go-ahead for publish + packager change.
**10-08 00:45:** all 779 packages covered: 692 via IFC jobs, 87 DB1/SDS2-only via 268 non-IFC jobs now ON THE FLEET (jobs_v7,
total 12,735 jobs; per-job "code": "db1"/"sds2" -> code_db1.tgz / code_sds2.tgz, ifc_key = regenerated/emitted IFC on bench S3).
73 class-1 rows are the same model in a 2nd package (jobs dedup by model_id; db1 jobs carry also_pids) -> publisher must
copy scripts into every package holding the model. Live page TOTALS now 12,735.
