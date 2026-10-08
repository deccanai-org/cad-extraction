---
name: project-db1-step-conversion
description: "Tekla DB1->STEP re-run state (2026-09-25): code-version reruns, hold flag, decoder facts learned (8.5x plate outlines, chamfers, flagged records, axis/column guards), fleet + credential limits"
metadata:
  node_type: memory
  type: project
  originSessionId: 7c4aa40f-8a98-4322-9286-b3fa20c9602b
  modified: 2026-09-25T23:50:51.830Z
---

Workspace: /Users/dhiren/Downloads/Deccan/cad-db1-convert (src/ = decoder + worker; S3 mirror
s3://annotationprod/cad-disk-extract/_control/db1-v2/src/). Results: `_state/db1-v2/results/<sha>.json`,
STEP: `conversions/db1-step/<sha>.stp`. User order (2026-09-25): finish ALL DB1->STEP first, THEN package
everything at once (projpkg4 3d/2d via src/pkg_step.py).

**Run history:** first pass finished 2026-09-25 04:20 UTC (~7,190 OK of 9,110 approved-version files);
fleet self-terminated on DONE. Re-run on code `db1-2026-09-25b` launched 04:59 UTC: 9x r7i.16xlarge
Mumbai + 4x r7i.16xlarge Hyderabad (ap-south-2c; 2a/2b had no capacity) + cad-db1-re c7i.24xlarge
= 928 vCPU; 25 engine versions approved (7.52..9.08; only 5 banner-less "None" files excluded).

**Deploy mechanics (no purge needed):** worker constant `CODE` + `KEEP` {older code: statuses still
valid}; anything else re-runs when workers cycle at the end of their rounds (no kill needed). Code
history: b (04:59 relaunch) -> c (find_members crash, truncated gzip, exact COLUMN name check) -> d
(web-vertical guard judged on horizontal I-sections only; angles/pipes/purlins caused false holds).
`ok` outputs are identical across b/c/d. Non-ok re-runs delete stale STEP.
**Packaging (2026-09-25):** src/pkg_step.py, PKG_SOURCES=ifc|db1, PKG_SHARD=i/N (one Python process
is GIL-bound at ~1 core: run many shard processes). IFC pass on cad-pkg-step-ifc (Mumbai, shards
0-13/30) + cad-pkg-step-hyd (Hyderabad, 14-29/30) with retry loops. Then DB1 pass, then `retag` (adds
`step_source` native/ifc/db1 to every STEP row; old Windows-pipeline STEP = source_key under
derived/db1-step). Both IFC- and DB1-derived STEP kept side by side (suffix on name clash). S3 key
`_control/db1-v2/hold` stops workers from writing DONE (remove it at the very end so the fleet shuts
down). Relaunch = `src/launch_fleet.sh` (Mumbai vCPU guard <=700 built in). Backup of prior code:
`_control/db1-v2/src_backup_2026-09-25a/`.

**Later codes (2026-09-25):** e = per-part axis check with 15 deg tolerance, bolt groups excluded
(end-offset braces tilt 5-9 deg; wrong links give ~0.1 agreement). f = plausibility bounds on
PARAMETRIC profiles only ('RB8534.4' = 28 ft parsed as an 8.5 m round bar hung ifcopenshell 0.8.5):
round bars RB/ROD/RD/DIA <=300 mm, other CIRC <=1500, studs <=100, anchors <=150, CHS <=3000, RHS
<=2000, L <=1000, plates/panels only absurd >50 m (400+ mm contour plates are real modelled objects);
catalog never rejected. f re-ran every OK file. ifc2step5 defaults to one tess thread PER CORE PER
JOB -> 60 jobs x 64 threads thrashed big models into 3 h timeouts; worker now passes --threads 4.
**Code g (12:25Z 2026-09-25):** ifcopenshell 0.8.5 (fleet occ env) HANGS forever tessellating HSS /
IfcRectangleHollowProfileDef members with IfcBooleanResult cuts; 0.8.4.post1 converts the same model in
minutes. Worker builds /opt/ifc84 venv (pip ifcopenshell==0.8.4.post1) and runs ifc2step5 with it;
f results kept except step_fail. Probe tool: _control/reports/hang_probe/probe_par.py (per-element
subprocess mesh with timeout, run with the fleet env python).
**Packaging hang:** single CopyObject of multi-GB STEP sat 3 h in an SSL read (no timeout fired) ->
pkg_step now uses connect/read timeouts + standard retries + multipart copy above 1 GB.
**End-game automation:** _control/packaging/endgame/ (endgame.py conditions + eg_mum.sh/eg_hyd.sh on
the two packaging boxes) sequences IFC round1 -> DB1 final -> DB1 pack -> IFC finishing (worker idle
hook runs ifc_finish.py) -> fleet release (delete hold) -> IFC round 2 -> retag -> self-shutdown.
**Vcpu cap trap:** launch guard counted only Project=cad tags; the old Windows converter
(cad-db1-step-windows-01, 96 vCPU, Project=cad-disk-extract, dead since 2026-09-24 19:13) was missed ->
Mumbai hit 784. Classifier blocked stopping it (ask-first box). Guard now counts both tags.
**Parallel fork session** of this conversation existed (c9491d) and edited shared files; coordinate
via SendMessage before touching production.

**IFC output audit (2026-09-25 ~14:00-15:00Z):** "empty" hid failures. Of 357 empty IFC results, 353 are
complete grid-only files (341 Tekla GridExporter), 3 are TRUNCATED SDS/2 copies (no END-ISO, 14k-121k dangling
refs; intact copies of the same exports converted fine) and 1 was TWO exports concatenated (ids restart at #1)
-> fixed by src/ifc_concat_fix.py (renumber later block; fold its IfcProject into the first: with 2 IfcProjects
ifcopenshell silently drops the mm unit -> 1000x geometry). Scan of all 9,129 IFC (src/ifc_concat_scan.py,
81 s on the RE box) found only that one. 4 "ok" outputs had astronomically large bbox: the SOURCE IFC holds
corrupt IfcCartesianPoints (2.6e266); exact path wrote orphan points -> src/ifc2step5_guard.py tessellates
such elements; swapped into conversions/ (old results in _state/ifc-step/results_superseded/); packaged copies
swapped by report_final/replace_repaired.py AFTER endgame. Big bbox otherwise = real georeferencing (state plane).
**DB1 worker bug fixed 14:25Z:** watchdog deferral `int(x*1.6 >> 30)` -> TypeError, so killed jobs never
released (claims go stale after 40 min). Fixed line deployed; takes effect on worker restart.
**DB1 STEP hang (Trex HQ 8.85, 44 versions):** one W27X84 piece with flange cuts 0.00024 rad off-axis ->
near-coplanar OCC boolean loops for hours. Fix (deployed ~15:25Z, CODE still g): db1step.cut_frame snaps cut
axes within 1e-3 rad of the part's axes (regression: identical parts/faces/bbox, max change 0.0033 deg);
worker WRITER="cut-snap" + done_now re-runs any g step_fail lacking the writer tag once. Old-code processes
cannot be killed without SSM -> they time out 18:30-21:00Z, then re-run. Classifier BLOCKED adding a GATE job to
db1_jobs.json ("Modify Shared Resources") -> last re-runs may miss the box's DB1 plan: place them post-hoc with
src/pkg_step_posthoc.py (PKG_STATE private prefix, PKG_NO_MOVES=1) after endgame_done, then re-verify shards.
**IFC crash rescue (15:30Z):** ifc_finish.py (= _control/db1-v2/idle_hook.py) gained a pass for finisher
convert_fail rc -11: src/ifc_crash_bisect.py (parse once, fork batches, split crashing batches) + src/ifc_exclude.py
(drop only culprit representations), record excluded_elements. 16:04Z added strict tail repair (file cut mid-statement: drop only the unfinished tail, accept iff 0 dangling refs +
IfcProject + units) -> rescues fdc6a1e482 (Tekla 18.1, 49 bytes lost); refuses aa537ffa59 (garbled from 85%, 105k
dangling, project/units in the damaged part). Remaining IFC fails are source defects:
3 all-zero files, 2 OLE2 docs named .ifc, 1 24-byte stub, 3 truncated SDS/2 copies, 2 CIS/2.
**ARC BUG (found 17:40Z via no-fabrication check, fix "arc2" deployed ~18:10Z):** apply_chamfers emitted
one arc per type-40 point, so consecutive arc points (Tekla round plate = square with all 4 points type 40)
duplicated arcs -> self-intersecting loops (Emory Bridge: 420/6,762 outlines; OCC segfaulted). Also overlapping
type-20 roundings on one edge crossed. Fix: edge-by-edge arcs (all-40 square -> circumscribed circle), overlapping
roundings shrunk proportionally, refuse only treatment-induced crossings (Tekla often stores contours whose last
point sits a hair past the first: keep those as stored). Old routine kept as _apply_chamfers_v1 to count
arc_stats.changed; worker re-checks every ok output with contour plates on a poly_ch layout: changed==0 ->
keep STEP (arc_check=unchanged), else rewrite. Packaged copies of rewritten outputs need a refresh pass.
**Pairs check (src/compare_pairs.py):** most pairs.json "pairs" are NOT the same model (IFC in the folder is
another job); only profile-overlap >=0.9 pairs count (HDK 100%, GSK 98.5%).
**Laptop uplink ~0.3-0.8 MB/s** (234 MB STEP = 12 min); S3 Select is NOT enabled (MethodNotAllowed).

**End state (2026-09-25 ~23:50Z):** end-game ran fully (endgame_done 22:14Z, boxes self-terminated). Coverage audit
of every packaged DB1 vs every attempt: 23,294 distinct DB1 in dataset = 12,513 model DBs + 10,781 `xslib.db1`
(Tekla component libraries, NOT models; original pipeline skipped them too; a few xslib-named "conflicted copies" are
real building-scale models and stay converted). 40 model DB1s NEVER attempted by anyone (nested zips / late
archives) + 1 left UNKNOWN (827-byte 6.87 stub) -> appended to db1_jobs.json (backup db1_jobs.before_never_attempted_2026-09-25.json),
40/40 converted, stub = no_member_layout. Scope now 9,609; 8,837 ok incl. 865f (rescued: 1 hanging W16X26 excluded).
**Packager gap fixed:** 123 packaged DB1 copies had an OK STEP but none placed: identical content, but source uploaded
with a different multipart layout -> different SOURCE ETag. Fix = also match by the PACKAGED object's ETag+size
(scratchpad pkg_posthoc_run.py; state _control/packaging/step_v1_db1_posthoc = 179 placements, 82 moves 2d->3d; posthoc2 = 865f).
**Old-pipeline defect:** its FAILED runs ("no solids written") wrote header-only STEP (PRODUCT + empty shape rep);
original packager copied 168 of them into 43 projects. empty_step.py (scratchpad) plans removal; classifier BLOCKED the
delete step -> needs user OK. Same for STEP dedup (31 identical STEP rows / 25 projects, dedup_step.py).
**Infinite-vertex defect:** 2 DB1 STEP (b5e0694a4b02 Littleton, 9c2e39cb0fcf 4040_OWC) held tessellated vertices at
OpenCASCADE's infinite bound (2e100 m -> 2e103 mm); nondeterministic (re-run clean, same parts). Regenerated via
regen_step.py on the last fleet box; old results in _state/db1-v2/results_superseded/. Check every output's recorded
bbox (DB1 step_stats / IFC stats) for |v|>1e10 mm; 67 big IFC finisher outputs have no stats -> scanned by grep.
Bend Surgical (50 versions): one real stray W16X40 ~100 km out, genuine model content. IFC ~3,040 km = Texas Central state plane.
**Classifier:** blocked (a) worker idle-exit change, (b) dataset deletions; allowed SSM runs, jobs append, hold re-create,
terminating idle fleet boxes. Hold flag re-created 23:48Z to keep ip-10-0-102-40 (i-04e8d4fbac5c1013e) alive; REMOVE
it (SSO delete) when done so that box shuts down. Windows box cad-db1-step-windows-01 still running: user's decision.

**Credentials:** SSO `annotationprod-publish` is the only identity with SSM + RunInstances + S3 delete;
the IAM user profile `bim` can only get/put/list S3 + describe EC2. When SSO expires, run
`aws sso login --profile annotationprod-publish --use-device-code` and have the user approve the code.

**Decoder facts learned (all IFC-validated):**
- 8.5x+ contour plates: part +29 -> stride-33 link record +25 -> stride-341 outline (2-hop).
- Outline record (7.82/8.07/8.53): u[10]@21 v[10]@61 w@101 chamferX@141 chamferY@181 type@221
  (INT_MAX after last point); >10 points continue in records with the same key, index at +13.
  Chamfer types: 10 line, 20 rounding (tangent arc, radius X), 40 arc-point; 30 unknown (kept sharp).
- 8.65 (Dutch model): part-attribute records flagged 0x01 and name strings 0x05 instead of 0x04
  live outside the runs -> batched `Db.flagged()` lookup. No PART records use other flags.
- Orientation guard: member csys x must lie along its own p1->p2 line (1.0 on every validated model;
  a wrong link scored 0.117 while still "web-vertical" 1.0). COLUMN-named parts must be >=70% vertical.

See [[feedback-userdata-shutdown-trap]] and [[project-cad-extract-pipeline]].

**FINISHED 2026-09-26 05:26Z.** All 9,609 DB1 jobs final (8,837 ok; Teton a3200ff/f8f6 re-run with hang rescue, 1 element
each excluded). Final verify: 2,476 packages (1,286 3d / 1,185 2d / 5 empty), 34,270 STEP (6,220 native / 14,652 IFC /
13,398 DB1), every check 0, 0 duplicates. Report (final) https://claude.ai/artifact/KHobBDtMgY9auop34PnBzH ; status page
commit 2a9a13b; simple owner tables: artifact 2pciktz1F3VwjdpYTATVZg + Google Doc "Locked and Damaged Files"
(13Z-vAA1xTElI-SPR-VmNwn3V6d2WGTPctADczAD96HM) + report_final/out/simple/*.csv/.xlsx. Hold removed 05:22Z; last box
terminated; only the lead's cad-disk-extract-hyd-medium/-status remain. Extraction leftovers rebuilt from raw EC2 records
(report_final/raw/): 1,307 locked nested zips / 38 archives / 41,088 files; 55 unopenable nested archives / 25 archives;
7 damaged. Baseline-era 2,507 archives logged no nested detail. OPEN: old superseded copy at cad-disk-extract/packaged/
(~18M objects) awaits the user's delete decision.
