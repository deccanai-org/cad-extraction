---
name: project-partial-tier-parametric
description: "Partial tier (3d_partial, 26,733 class-2 STEP) -> perfect build123d scripts: the 5 sample models chosen 2026-10-07 and the gap-analysis workflow"
metadata:
  type: project
---

Dhiren (2026-10-07 evening): after the perfect-tier pmx run, assess what it takes to turn the PARTIAL tier
(dataset/packages/3d_partial/, 2,418 projects, 26,733 class-2 STEP: db1 13,883 approx; ifc 6,475 approx + 1,996
complete_to_source; sds2 4,363 approx + 16 c2s; 18.7 TB STEP, medians 180-300 MB) into perfect build123d scripts.
He wants the 5 samples shown FIRST before any analysis ("no first give me the 5 samples").

Samples (per-model partial record = package manifest.jsonl row "partial" {kind, issues, missing[], standins[]}):
1 IFC c2s HARRIS_RESTAURANT_JOB (SDS/2-authored IFC, 1,733 parts, 13 open shells in source) - TEKLA-HYD SDS2-TEAM 105 to 110
2 IFC approx 182714-0015_Texas Live Hotel_IFC (Tekla, 1,885 parts, 1 part >5% vol) - CMC-ALAMO 45. Texas Live
3 DB1 light 32-25006 AUS Atrium Infill ABM (979 src / 951 step, HSS radii, rebar profile missing) - CMC Alamo S Drive
4 DB1 heavy 32556_Spirit Square Building-87e213 (coverage 0.785, 417 parts no profile, 117 slotted holes round, studs,
  bolts/washers nominal) - Steel Fab 35. New Main Library (add-on; DB1 in perfect package; ~215 versions)
5 SDS2 Building_J_Exp._JOB-88ffc7 (558 parts, 24 open-web joists from designation, 97 guessed bolts, 352 mating holes)
Tier-wide issue counts: report_v1/data/partial_issues.json (top: slotted holes 11.5k models, studs 8.6k, bolt fit 7.7k).

Workflow partial-5-gap-analysis (run wf_988f2e2f-1f0, launched ~17:45 PDT 10-07): analyst + skeptic per sample on held
boxes (i-0eaaa4ab9c78b6488, i-044e7693566bfebef, i-0a8e721cc7429893e, i-017d6427d1ba2e850, i-0d3e1ca73ea6876de),
then synthesis -> scratchpad (session 5462df30) partial/<sample>/REPORT.md, SKEPTIC.md, partial/SYNTHESIS.md.
Reuses DB1 IFC regen (proven byte-identical-modulo-ids; GUID restore) + SDS/2 IFC emitter from the previous session:
scratchpad (session f63cb79e) full/nonifc/{db1_regen, sds2_emitter, code_db1, code_sds2}.

Related: [[project-pmx-full-corpus]], [[project-zenitude-report]], [[project_db1_step_conversion]]

**10-07 evening:** Dhiren opened the 5 delivered STEPs (~/Downloads/partial_5_samples/, original names; _extra/ = source
IFCs + manifest rows) in CAD Assistant and asked "where is it bad". Coordinates/GUIDs alone were not useful to him -> made a
colour-highlighted copy of the STEP (build123d on bench i-0f35da72bf742063d: grey ok, RED missing parts rebuilt from the
SOURCE's recorded geometry, ORANGE approximated, YELLOW to-check; labels = STEP product names, not GUIDs).
Sample 3 findings: missing = a 165.1 mm 3000-psi concrete SLAB (profile "165.1" unrecognised; outline in DB1 record,
x 381-60579, y 11963-35585, top z 157267), 26 #4 A706 rebar, 1 no-profile part; orange = 6 HSS24X24X1 front columns
(corner radii assumed), 1 bolt fitted; yellow = 36 L2X2X1/4 railing posts split at slab level. Template:
scratchpad overlay/make_overlay.py. Workflow partial-issue-overlays (wf_66d31fe5-b7e) builds the same for samples 1,2,4,5
(+ PURPLE = parts our script does not yet rebuild perfectly) -> scratchpad overlays/<key>/ -> copy to Downloads.

**Gap analysis DONE 10-07 ~19:40 PDT** (workflow wf_024421b5-816; full result incl. synthesis in session 5462df30
tasks/wmhcqfhmg.output - agents did NOT write REPORT.md/SYNTHESIS.md files). Per sample: s1 1,695/1,733 match -> 1,715 after
duplicate-GlobalId fix (20 anchors share 2 GUIDs), 18 rod-bracing parts open in source; s2 1,846/1,885 (analysis incomplete;
B16355 beam 99.97% missing in delivered STEP, not just "1 part >5%"); s3 978/979 recoverable from package data (rebar +
HSS radii from sibling profdb.bin, slab via bare-number contour route, T profiles); s4 coverage 1,578->2,008/2,009 after
~2 days decoder fixes (Latin-1 strings drop 416 nuts/washers/rods, bare-number concrete, bevel loops) but slots/studs/
bolt placement need rules or profdb decode; s5 558/558 vs own IFC but 24 joists stand-ins (never from package), 97 "guessed"
bolts actually have SDS/2 f32 records. Key truths: manifests UNDER-report gaps in 5/5; DB1/SDS2 "perfect" is CIRCULAR
without a truth layer (NetVolume, kernel-fallback detector, GUID joins); model-level perfect stays rare (DB1 readiness audit:
perfect only after ~6+ families fixed); 70% of partial bytes are >=1 GB models the pipeline can't run (extract OOM >8 GB).
Owner decisions needed: rules as authority (slots 94.5% on 8.85, bolt placement, panel orientation), filling one missing
face, sibling-folder profdb as source. Agents also made a duplicate download set ~/Downloads/partial_tier_samples/.

**Modal pipeline (pmp) started 10-07 ~20:15 PDT.** Dhiren: run the same per-model process (source IFC -> build123d scripts
+ verification -> colour-highlighted issue STEP + WHERE_TO_LOOK) for ALL partial models on MODAL; test on the 5 first,
then scale. Modal client: ~/Downloads/Deccan/partial_modal/.venv/bin/modal (1.6.1), token in ~/.modal.toml profile
"navaneeth" = workspace navaneeth (billing goes there). Design: NO AWS keys on Modal - inputs via 7-day presigned GET URLs
(AWS_PROFILE=bim), outputs to Modal Volume pmp-out, copy to S3 later from EC2. >=1 GB models out of scope v1.
Cost heads-up given: AWS egress ~$1.8-2.5k for ~20 TB inputs; Modal compute likely tens of $k -> get measured per-model
cost from the 5-sample test BEFORE scaling and ask Dhiren. Build workflow pmp-modal-build (wf_6d67eeae-7e4): components in
~/Downloads/Deccan/partial_modal/{jobs,src_db1,src_sds2,overlay,app,code,docs}, test results -> test5_results/REPORT.md.
All 5 sample overlays + WHERE_TO_LOOK notes delivered to ~/Downloads/partial_5_samples/ (s4 checker pending at 20:06).

**10-07 ~21:00 PDT - Modal approved explicitly by Dhiren** ("just do using modal") after the auto-mode classifier blocked
the first launch as Data Exfiltration (client data -> external Modal workspace navaneeth). Requirements added: shipped
scripts/<model>/build_issues_model.py (rebuilds the colour-coded model from schedules; --from-delivered colours the delivered
STEP via text-level name edit + appended styling = byte-identical geometry, small files) and PUBLISH everything into
dataset/packages/3d_partial/<pid>/scripts/ (layout: README, requirements, steelbuild.py, issues_lib.py, scripts_manifest.jsonl,
<model_folder>/{build_model.py, build_issues_model.py, model_info.json, schedules/ incl. missing_parts.json + issues.json,
verification/, issues/ (ISSUES_highlighted, MISSING_parts_only, WHERE_TO_LOOK.md), source/}); never touch files outside
scripts/; package manifest.jsonl untouched. Publishing path: Modal -> presigned PUT (made on EC2 i-0f35da72bf742063d with its
role) -> _state/pmp/bundles/<run>/<model_id>.tar.gz -> publisher on that box merges into scripts/. Test B = new5.json:
n1 DB1 51_Westwood_PETCT_Master, n2 DB1 add-on F232-MASTER-d6c7cd, n3 IFC approx 31-2214 GCP3_STL-e7a9c8, n4 IFC c2s GRID3
(MMW P535 Hangar), n5 SDS2 BACKUP_DATA ROOM_1021. Workflow pmp-modal-build-v2 (wf_cf70d4b6-df4). Scale only after Dhiren
sees cost.

**ASSIGNMENT CLARIFIED (Dhiren 10-07 ~23:00 PDT):** the goal is a COMPLETED, perfect-looking model per partial package:
fill in ALL missing parts + CORRECT approximated parts, colour-coded, and ship scripts that BUILD THE COMPLETED MODEL (not just
a diagnostic map). Colour scheme agreed: GREY original confirmed, GREEN restored exactly from source data (DB1/SDS2/IFC fields
the converter ignored), BLUE rebuilt from cited industry standards (bolts/nuts/washers/studs/rebar/HSS radii/SJI joists/grating;
labelled 'standard-based'), ORANGE still approximate (no data, labelled). Completion tracks (agents, 10-07 23:00):
complete/db1 (slots, fittings, Latin-1 strings, bare-number concrete, bevel loops), complete/standards (library),
complete/sds2_ifc (SDS2 f32 bolt records, anchors, mating holes; IFC per-operand boolean rebuild, >5% parts, one-face shell close).
Baseline diagnostic run (5 new samples) published: Westwood (n1) + Data Room (n5) in their packages' scripts/; Westwood files
downloaded to ~/Downloads/Westwood_partial_check/. Live page https://dhigdec.github.io/cad-extract-status/partial.html
(publisher partial_modal/status/publish_partial.py loop, anonymous numbers only).
**10-07 ~23:15 PDT: completion workflow pmp-complete-5 (wf_04d495a5-e66, ultracode)** replaces the 3 stopped agents.
Final colour code: GREY original verified, GREEN restored from source data, BLUE cited standards, AMBER estimated (basis
stated), MAGENTA our script differs (target 0), RED marker only (target 0). Deliverables per new sample: ORIGINAL.step,
<model>_COMPLETED.step (coloured) + _COMPLETED_plain.step + CHANGES.md + scripts (build_model.py builds the completed model,
build_completed_coloured.py), published to package scripts/<model>/completed/ and copied to ~/Downloads/partial_5_completed/.
Code: partial_modal/complete/{db1,sds2_ifc,standards,estimate,INTERFACES.md}, app_v2/ (completion stage; app/ left for baseline).
