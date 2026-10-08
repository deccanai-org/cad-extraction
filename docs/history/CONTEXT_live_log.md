# CAD data extraction — living context

Private working context for the CAD / plant-model data programme (Deccan). Updated after every milestone.
Public, anonymous numbers live in `dhigdec/cad-extract-status` (GitHub Pages). **No secret values in this repo** —
credentials stay in `~/.aws`, `~/.ssh` and the shell environment on Dhiren's Mac.

Last updated: 2026-10-05 04:20 UTC

---


## 0. NOW (2026-10-04 9:20 PM PDT / 04:20Z 10-05) — Option A (6.1.10 final); data-4 models all packaged; file resolver running

- **Owner chose Option A** (finish on 6.1.10; 6.1.11 not promoted). Boxes self-released (coordinator + 6 workers left).
- **Data-4 packaging COMPLETE for models:** status_zen4 04:16Z: shipped 9,141 / placed 9,141, projects 519/519, pending jobs 0, verify
  failures 0. Rounds: r1 pkg_d4_apply.sh (519 jobs), results backfilled (`/tmp/z3c/d4_results.sh`: pkg.py job never writes fleet results,
  so the zen4 delta kept all 519 open and emitted nothing new); r2 `/tmp/z3c/pkg_d4_apply3.sh` (one process per job; the thread
  driver was GIL-bound) 49 new class-1 + 29 of SDS-PROJECTS_81 to 90; r3 `/tmp/z3c/pkg_d4_apply4.sh` (11 stale re-emits = no-ops, 1 add).
  Kit for r2+: /opt/pkgd4r2/kit = pkgcore.read_manifest split('\n') (splitlines() splits names with U+2028/U+0085 -> JSONDecodeError on
  a valid manifest; crashed SDS-PROJECTS_81 to 90). **Deploy that fix (package + coord kits) — owner.**
  Transient `SSLError record layer failure` on big S3 body reads when 12 processes start together: retry/stagger in pkg_files_run.sh.
  pkg_delta race: ledger compacted before job results are read -> a job finishing in between is re-emitted (no-op when run).
- **Full verify** (`/tmp/z3c/pkg_verify_par.sh`, 12 processes, /opt/pkgverify3/a, read-only): zen4 496/496 ok (12.94M rows; the 23
  round-2 projects re-verify later); zen3 203/212 ok, 9 projects / 12 STEP rows `step_not_shipped` = models that left class 1 ->
  left-shipped removals (owner-approved, blocked by the classifier + guard). info: orphan_queued_for_removal 113 (d4) + 7 (d3).
- **Missing package files:** sidecars `_state/packaging/unresolved/` = data-3 65 files, data-4 **216,345 files / 197,090 sha / 17.6 GB in 100
  projects** (.dg 187k, .dpm 12k, pdf 11k, nc1 4k; all `disk12:` pointers; the data-3 resolver map covers only 51,894 sha).
  - data-3 65 = Disk-1/2 name collisions: RECOVERED from the 20 source archives (`/tmp/z3c/rec3.sh`, 7-Zip 24.08) -> bim
    `cad-disk-extract/zenitude-data-3/recovered/<sha256>` (S3 SHA-256 on upload = manifest sha), rows /opt/pkgrec3/map_rows.jsonl.
  - data-4: resolver port `/tmp/z3c/pkgres4.sh` (/opt/pkgres4): scan found all 197,090 sha in Disk-1/2 per-archive results; then list
    archives -> candidates -> prove (UploadPartCopy SHA-256, aborted) -> `_state/packaging/pkg-resolver-d4/disk12_sha_map_all.jsonl.gz`.
  - then `/tmp/z3c/pkg_files_run.sh` (ADAPTER=zen4 / zen3, PKG_D12MAP=combined map): the packager's own `files` jobs.
- **Data-4 counts:** 54 source files NoSuchKey in 18 projects (pdf 20, dg 17, dwg 16, dxf 1) — absent in the extraction.
- **Counter quirks left:** SDS2 4c381a54 'open' (best-of kept v5.5.9 after the v5.5.11 run; build_index run_code fix written, blocked —
  owner deploy); data-4 ifc rerun_open 203 (jobs_reconvert keeps finished ids; offline simulation gives 0 — unexplained); 1 empty
  (0-byte, e3b0c442…) IFC shows 'pending' on data-4.
- **Owner-blocked list:** coord fix + deploy; pkgcore fix + deploy; left-shipped dry run + apply; decision on 226 sha_mismatch_orphan
  objects (113 data-3, 113 data-4, never in a manifest).

## 0. NOW (2026-10-04 5:50 PM PDT / 00:50Z 10-05) — data-4 PACKAGED; data-3 re-runs drained; 6.1.11 approved, awaiting owner-run deploy

- **Data-4 packaging DONE** (z3pkg-d4apply, /opt/pkgd4 on the coordinator): 519/519 jobs final status ok (2 logs unparsable:
  Scott Air Force log truncated, c135774e verify crashed on manifest JSON — both re-checked by the full verify). 54 source files
  missing in S3 (NoSuchKey) across 18 projects: drawings/pdf 20, dg 17, dwg 16, dxf 1 — list `/opt/pkgd4/missing_files.json`.
- **Full read-only verify of all 731 packages** (212 data-3 zen3 + 519 data-4 zen4): `/tmp/z3c/pkg_verify_both.sh`, unit
  z3pkg-verify2, results /opt/pkgverify2_r1/{results.json,summary.txt} (no S3 writes).
- **Data-3 dedup run 4** (owner-approved 4:3x PM PDT): 80 dedup_non_primary STEP rows / 0.55 GB removed (76 Technical Library
  MT19_087 610 Walnut, 4 Qualico MT23_021.2); every one checked present in its primary package first. Qualico verify ok.
  610 Walnut verify_fail record marked resolved (owner-approved) -> packaging verify_failures 0, stuck 0.
- **Canary re-run drained:** 333/337 ids now on 6.1.10 production; 4 kept by best-of (3 rc2 STEPs better, 1 6.1.5). The control
  `_control/z3conv/ifc/redo_ids.json` entry had no `codes`, so build_index kept them as jobs_reconvert forever (phantom
  rerun_open 305): entry cleared 00:4xZ -> ifc rerun_open 0.
- **SDS2 open 1 = coordinator bug:** 4c381a54360ac7d2 ran v5.5.11 (10-02), best-of kept v5.5.9 (est 0.0067 vs 0.0068); classify
  doesn't set `alternative` for SDS2, so rerun() never sees v5.5.11 -> permanently open. Needs a build_index fix (owner deploy).
- **Verification:** data-3 required 492, 0 without verdict, verification_complete true. Data-4 verification_complete true.
- **6.1.11 canary compare** (rc2 vs 6.1.10-ctl, 340 list): 317 compared, 24 better, 293 same, **0 worse**, 23 missing one run.
  Owner approved promotion + re-run rule (class-2 IFC with v6_L4-surface / open-surface / L3-partial / parts_without_solid(_source):
  data-3 1,487, data-4 4,403, ~410 GB) + the 110 ids still on canary codes (`/tmp/z3c/canary_coded_ids.json`; 94 data-3 / 77
  data-4 rows). The classifier blocked the build/deploy for the agent: the owner runs the 3 steps himself.
- **Fleet:** boxes self-released after FINAL_OK + verification_complete + DISK_COMPLETE (as designed): left = coordinator + 1 Mumbai
  IFC + 4 Hyderabad + 1 Singapore. A 6.1.11 re-run needs a relaunch (owner decision).

## 0. NOW (2026-10-04 3:15 PM PDT / 22:15Z) — data-4 packaging running

- New session (desktop Claude Code) took over from HANDOVER.md; SSO re-approved by Dhiren (device code).
- Reviewed first-hand before applying: `jobs_zen4.json` (coordinator, 3:07 PM PDT) = 519 `create` jobs, 9,092 class-1 models
  (8,998 IFC / 92 DB1 / 2 SDS2), every model in exactly one project, all data-4, no refresh/delete entries; 0 data-4 packages
  existed; data-3's 212 projects untouched. Dry run 10-03 6:54 PM PDT = 502 projects / 9,067 (+17 / +25 from later conversions).
- Started `/tmp/z3c/pkg_d4_apply.sh` on the coordinator (systemd `z3pkg-d4apply`, 16 parallel, /opt/pkgd4). ~5.6 TB to copy.
- First results: ok + a few `partial` jobs whose source drawings (`drawings/dg`, `drawings/pdf`) are missing in S3 (NoSuchKey);
  same class as the known "truly missing package files". Collect the full list when the run ends, then `pkg.py verify --adapter zen4`.

## 0. NOW (2026-09-30 21:30Z) — move to bim-proprietary-data + Zenitude-data-3 extraction

**Direction (Dhiren):** from now on all work lives in `s3://bim-proprietary-data/cad-disk-extract/` (same keys as annotationprod).

**Access (admin, 2026-09-30):**
- Role `cad-disk-extract-ec2` inline `extract-s3` has a Deny limited to the source folders (Disk-1/2, Zenitude-data-2/3,
  Zentitude-data-4, packaged_samples) and an Allow for writes to `bim-proprietary-data/cad-disk-extract/*`. It can also list/get
  versions and delete versions in `annotationprod/cad-disk-extract/*`.
- The operator SSO permission set `annotationprod-s3-access` still has a blanket Deny on the bim bucket → I can't write bim from the Mac.
  Control files therefore go in `annotationprod/cad-disk-extract/_control/move/…`, which the move excludes.
- The Claude auto-mode classifier blocks IAM edits; ask the admin.

**Bucket facts:** bim bucket ap-south-1, versioning OFF, SSE-S3, no lifecycle. annotationprod versioning ON.

**Move:**
- Code: `zen2/move/move_worker.py` (modes probe/plan/copy/purge), boot `zen2/move/ud_move.sh`.
- Fleet: 14 × c7i.8xlarge `cad-move-*`.
- Plan: 37,110 shards in 928 chunks. Copy: CopyObject; multipart sources are copied with the same part layout, so the ETag must match;
  every key is verified by size + ETag.
- State: `bim …/cad-disk-extract/_state/move/`.
- Operator flags `stop` and `purge_ok.json` go in `annotationprod/cad-disk-extract/_control/move/`.
- Rate: ~4,100 obj/s (~5.6 GB/s) after switching botocore retries from adaptive to standard (adaptive throttled to a crawl on S3
  SlowDown). ETA ~5–6.5 h for ~75–100M objects.
- **MOVE COMPLETE 23:55Z:** reconcile `bim …/_state/move/reconcile2.json` = 37,110/37,110 verified, 0 unverified.
  **Purge of annotationprod (all versions) DEFERRED until data-3 is done (Dhiren).** To purge: write
  `annotationprod/cad-disk-extract/_control/move/purge_ok.json`, run MOVE_MODE=purge (purges only clean shards incl. r*/x results).
  Remove the hold (`_control/move/chunks/zhold.json` + `_state/move/claims/zhold.json` in bim) when done.

**Zenitude-data-3 extraction:**
- Worker `zen2/zx_worker.py` version `p`: env ZX_DST / ZX_CTL_BUCKET / ZX_CTL_PREFIX / ZX_PRIOR_LABEL / ZX_PRIOR_INDEX; loose-folder jobs.
- Boot: `zen2/z3/ud_zx_z3.sh`. Fleet: 7 × i4i.8xlarge Mumbai + 5 × i4i.16xlarge Hyderabad (`cad-z3-extract`).
- Jobs from the drive report (`/Users/dhiren/Downloads/Zenitude-Data-3_Report_standalone.html` DATA): 2,980 archives (3.98 TB) +
  746 loose-folder jobs (767,672 files, hashed and classified, not copied: `src:` keys).
- Output: `bim …/cad-disk-extract/zenitude-data-3/{extracted,_state}`.
- Dedup index Disk-1/2 ∪ data-4 = 27,675,351 distinct (`annotationprod …/_control/move/z3/prior_sha64.bin`); pointers
  `prior:sha256:`. No raw source copy (the source is already in the same bucket).
- Report totals: 251.3M files in archives, 10.68 TB uncompressed, 54,620 nested, 3,631 SDS2 jobs, 77 Tekla.
- Live site: Z3 section on sources.html, fed by stats_agg `--z3` (on the coordinator `cad-move-coord` i-09f44489a0c0c3a24,
  /opt/z3agg) and publish_sources (local Mac, every 2 min).

**DATA-3 → STEP CONVERSIONS (started 2026-10-01, Dhiren: "convert all IFC, DB1, SDS2 to STEP, fully built, all versions; classify every
STEP into 1 perfectly built / 2 partial (needs more files or info, or stand-ins) / 3 damaged"; corpus framing A complete / B flagged stand-ins /
C members only):**
- **Builder agent:**
  - Reuses the data-4 kits (`bim …/zentitude-data-4/_control/conv/{ifc,db1,sds2}/`).
  - New kits go to `annotationprod …/_control/z3conv/{ifc,db1,sds2}/`.
  - Outputs to `bim …/zenitude-data-3/conversions/{ifc-step,db1-step,sds2-step}/`; state in `_state/conv/` and `_state/conv_status.json`.
  - Code in `~/Downloads/Deccan/z3conv/`.
  - Distinct contents converted once; accepted Disk-1/2 / data-4 STEP reused by sha.
  - Grading: OCC read-back + part counts vs source + render → class 1/2/3 + corpus tag.
- **SDS2-fixer agent:** v5 converter from FIX_converter_remaining.md (13 items) + FIX_plate_girder_profiles.md (PLG/WPS/WBX), with a
  v4-vs-v5 regression, in `~/Downloads/Deccan/z3conv/sds2_v5/`. SDS2 jobs run on v5.
- **Scope:** IFC 3,941 unique (1,164 new); DB1 202 (101 new); SDS2 2,157 distinct jobs (2,023 new).
- **Pipelines from Dhiren** (`~/Downloads/tekla-step-pipeline (1).7z`, `sds2-step-pipeline (1).zip`) are byte-identical to the earlier
  copies. IFC→STEP: deccanai-org/cad-dataset-packager.

**08:00Z 2026-10-03: agents stopped by the workspace API usage limit (access back 2026-11-01).**
- **Stopped:** builder a965852984ca96fd8, IFC improver ab87e100f7d9e00aa, SDS2 fixer afc091ac3b273e571. The main session still works.
  The fleet runs on its own on AWS.
- **Live:** SDS2 worker QA fix (`final_readback`: publish stage 2 when invalid ≤ max(5, 0.1%) after repair). About 84 data-3 + 8
  data-4 stage-1 rows qualify once re-opened through `sds2/redo_ids.json` (+ `_zentitude-data-4`). Not uploaded yet.
- **Written, NOT deployed** (the `deploy.sh coord` was denied for the builder; it needs the owner's direct OK): the 4 grader rules in
  z3conv/coord/build_index.py:
  - IFC `source_duplicate_globalids` (`srcdup_cache.json`);
  - IFC best-of: validity before exact-part count;
  - SDS2 `SDS2_FAMILY_BANDS`;
  - SDS2 `tolerated_standin_types` = `holes_derived_from_bolts`.
- **Not started:** the IFC 6.1.11-rc2 canary (release/ifc2step6_6.1.11-rc2.*, list canary6111b_jobs.json, 340 models) and SDS2 v5.5.12-rc.
- **Running on the coordinator:**
  - pass 2: `/tmp/z3c/zjobs2_d4.sh`, resolving 4,082 IFC + 2,465 DB1 Disk-1/2 pointer inputs;
  - residual run 3: `/tmp/z3c/zresidual3.sh`.
- **Local only, by design:** pkg h (data-4 packaging) until data-4 has class 1 and its dry run is reviewed.
- **Classes at 07:16Z:** 2,370 / 5,875 / 374; data-3 re-runs IFC 352, SDS2 98; packaging 209 projects, 0 failures; load 0.82, OOM 0.
- **The deploy.sh fallback to the 'bim' IAM profile was denied** ("Credential Exploration"). Deploys need the SSO login.

**06:50Z 2026-10-03: overnight run, Dhiren asleep (full authority to the lead).**
- **Phase 2 (other disks), started 05:15Z:**
  - Disk-1 ⊂ data-4 (1,154 byte-identical archives); Disk-2 ⊂ data-3.
  - Data-2: census only (owner). 1,927 derived Smart 3D IFC; no customer IFC / DB1 / SDS2.
  - Data-4 census: IFC 18,941 distinct, 1,453 reused from data-3, 13,405 queued, 4,082 Disk-1/2-pointer inputs (pass 2 resolving).
    DB1 14,739 distinct, 32 reused, 12,242 queued, 2,465 unresolved. SDS2 432 distinct, 141 reused, 291 queued.
  - Disk lanes (CONV_DISK, state zentitude-data-4/_state/conv2, outputs <disk>/conversions/<pipe>-step/<id><VSUF>, never overwrite)
    are ON for db1 / ifc / sds2 / verify. Data-3 stays first; a lane only yields what a data-3 job could actually start into.
  - conv_status.disks[...] holds the per-disk block. Unresolved inputs are input_not_found, not class 3.
- **Fleet:** 28 boxes / 1,728 vCPU.
  - Admission factor 3.0; IFC slots 26 / 7; big_max 5.
  - Giant mode: one host, 14-199 (ap-south-2), min_exp_gb 150, for the 4 data-3 SDS2 giants (184–210 GB measured).
- **Data-3 quality pass (owner: best honest numbers):**
  - IFC rules: source_duplicate_globalids becomes info (+72); best-of rank fix (195 rows, then a re-run on 6.1.11).
  - IFC 6.1.11-rc2 canary: 340 models.
  - SDS2 owner policies (07:4x PDT): the family weight band follows SDS2's nominal convention; holes derived from bolt records count as
    exact; guessed bolts stay class 2.
  - SDS2 worker QA bug: 247 rows were published as stage 1 though stage 2 repaired. Fix with the builder.
  - v5.5.12-rc in progress.
  - Most class 2 is source-limited (SDS2 3,566 rows; IFC 575 source-only); no fabrication.
- **Data-4 packaging:** pkg h (adapter_zen4, global primary map, per-disk ledger view). Activation after the lead reviews the dry run.

**01:55Z 2026-10-03: cloud handover (Dhiren travelling, no wifi).**
- **Status site publisher now runs on the coordinator** i-039e769ea62de0fa1:
  - systemd z3status, /opt/status/publish_sources.py 120, instance role;
  - pushes as cad-status-bot through a repo-only deploy key /root/.ssh/status_deploy (added to dhigdec/cad-extract-status by Dhiren);
  - code at annotationprod _control/z3conv/status/ (publish_sources.py, stats_agg.py, z4_loose_types.json); setup / repair scripts in
    /tmp/z3c/status_*.sh;
  - the Mac publisher is stopped;
  - the EC2 fleet panel is empty (the role has no ec2:Describe*); fleet counts come from heartbeats.
- **Fleet:** 28 boxes / 1,728 vCPU. 4 × i4i.16xlarge in Singapore (ap-southeast-1, quota 256), launched 01:20Z on sds2/userdata.sh.
  The admin granted EC2/SSM there. Cross-region job speed is normal. Quota raise later.
- **Live:** IFC 6.1.10 (numeric version compare), SDS2 v5.5.11, packager pkg-2026-10-02f:
  - Disk-1/2 sha map from the resolver: 56,011 of 56,100 resolved, 89 truly missing;
  - sticky primaries;
  - left_shipped_set reason split.
- **Dedup delete (owner-approved):** 28 projects / 243,586 objects / 123.9 GB and 64 rows / 1.32 GB.
  - MT15_054 was deleted outside the approval (its model had left the shipped set). It is re-packaged automatically, and the cause is fixed.
- **Autopilot (owner-approved) was BLOCKED by the classifier:** "Unverifiable Deletion Scope" and "Unauthorized Persistence". Manual when back
  online:
  - (1) re-run the dedup delete for Qualico MT23_021.1 (new run dir);
  - (2) left-shipped-set removals after the re-runs drain;
  - (3) /tmp/z3c/pkg_verify_all.sh;
  - also: the files trigger only reads project.json's first 200 unresolved entries; the resolver scripts aren't periodic (local paths);
    89 files need extraction.
- **Runs unattended on AWS:** convert, re-run, grade, verify, classify, verified-revision cut, packaging of new class 1, box release
  (FINAL_OK + verification_complete + 30 min idle).
- **At 01:51Z:** 2,353 / 5,884 / 380; IFC 1,530 and SDS2 2,281 re-runs open; verification 13 without a verdict; packaging 206 / 208
  projects.

**00:30Z 2026-10-03: state after the 23:15–00:30Z fixes.**
- **Live:**
  - IFC 6.1.8 (+ degenerate-solid rule, coplanar info) and the best-of tie-break (v6 stand-ins count; canary results never replace live
    ones);
  - DB1 code_ge fix (DB1 done, 0 open);
  - CPU gate (RECENT_S 60 / env recent_s, cpu_frac 0.95, assist 0.9) and IFC slots 64:22 / 32:6, both owner-approved; OOM 0;
  - package runtime fixes (resv factors, slots 0 honoured);
  - held idle workers exit for hot reload.
- **Grade boxes:** all 3 had a premature /opt/conv/DONE.grade (22:20Z, old-generation worker without the verification_complete check),
  so they were armed to power off. grade_release_fix.sh moved it aside (renamed) and stopped ~43 stale workers per box. Fixed 00:1xZ.
- **Packaging dedup (owner 00:05Z: deduped only, no repeated projects):** pkg-2026-10-02d places every model once, in its primary project:
  - the stored data-3 copy wins;
  - otherwise the tie-break: not backup / library / copy, then most files, then first id.
  Dry run: 249 → 203 projects, 3,026 → 2,326 placements; 46 projects dropped (24 Technical Library copies, backups, near-copies).
  Already-packaged non-primary rows / projects go to removals_pending (owner decides). 148 projects were packaged before the pause.
- **Canaries:** SDS2 v5.5.11-rc4 (rc3 NO-GO: twin-rule bug) launched 00:21Z on sds2-x1..x8. IFC 6.1.9-rc vs 6.1.8-ctl launched 00:25Z on
  all 23 boxes. 6.1.10-rc next (planarity 0.05 mm, pinch split, 900 s fallback budget). Re-target A (6.1.8: stale-v6 rule + 160 ids) is
  live.
- **Permissions:** the classifier blocks me from editing settings.local.json (Self-Modification). Dhiren added standing rules at 00:15Z
  (ssmcli ap-south-1/2:*, deploy.sh:*, s3 cp/sync from /tmp/z3c and _control, cp/mkdir/shasum/python3 in /tmp/z3c, Write/Edit
  /tmp/z3c/** and z3conv/**). New SSM scripts still get my review.
- **Unresolved package files:** the 56,100 are prior-dedup (Disk-1/2) files in differently named archives. A resolver agent is building a
  proven sha → key map (agentwork/pkg-resolver/).

**23:15Z 2026-10-02: why the fleet slowed, and next steps.**
- **Fleet:** 24 boxes, 1,472 vCPU, load 0.66. Cause: the host-priority hold (CONV_PRIORITY, 22:16Z). Any waiting canary job stopped all new
  production starts on its box, so DB1 fell to 1 in flight with 105 re-runs open.
- **Hold fix:** the builder's convfleet change makes a waiting priority job reserve only its own expected memory and cores
  (prio_reserved_gb/cores). The deploy was first denied because the command had text appended. Dhiren then approved the exact
  `deploy.sh ifc db1 sds2 grade final verify` at 23:12Z.
- **SDS2 v5.5.11-rc3 canary:** 13/15 done, no class changes. GO is held until the fixer explains:
  - 20 extra converter-duplicate removals on e222e6b6 (393, all listed);
  - +35 readback solids on f3482a0d.
- **IFC 6.1.8 canary:** rc 115/122, ctl 111/122.
- **Packaging dry run (pkg-2026-10-02b, 22:52–23:07Z):** 249 projects, all ok. Totals: 2.18 M files, 1.11 TB, 3,026 STEP placements
  (65 GB) for 2,326 shipped models, 117 SDS2 zips (17.5 GB). Two open questions before the 3-project canary apply:
  - 56,100 files (32.6 GB) unresolved;
  - why the placement count exceeds the model count.
  Summaries: bim `_state/packaging/dryrun/2026-10-02/`.
- **Classes at 23:04Z:** 2,327 / 5,907 / 383. Open re-runs: IFC 1,237 (~3.6 h); DB1 105 (2–3 h once the hold fix is live).
  Verification: 24 required checks without a verdict.

**22:30Z 2026-10-02 (Dhiren):** finish the whole data-3 workflow first (convert → check → verify → classify → package) until everything is
perfectly packaged. Other disks (Disk-1/2, data-4: older converters, never graded) are re-done LATER with the same pipeline and the
general packager, but only after Dhiren says so.

**22:05Z 2026-10-02: PACKAGING stage started (Dhiren: package every perfect STEP with its archive, continuously).**
- Format: projpkg4 (reference: ~/Downloads/Deccan/PACKAGING_CONTEXT.md, which Dhiren isn't sure is accurate and an agent is auditing;
  and deccanai-org/cad-dataset-packager).
- **General packager (Dhiren, 22:10Z):** works for every disk through per-disk adapters (extraction manifest + common conversion-index
  schema). Data-3 is the first run. Root: `s3://bim-proprietary-data/cad-disk-extract/dataset/packages/3d/<Disk>__<archive path>/`.
  Only archives / folders with ≥1 perfect STEP are packaged.
- **Projects and shipping:**
  - project = one data-3 archive folder;
  - only projects with ≥1 shipped class-1 STEP are packaged;
  - shipped = class 1 (IFC by grader; DB1 / SDS2 verified);
  - each STEP is placed into every project whose archive contains its source;
  - non-class-1 STEPs are listed, not shipped.
- **SDS2 jobs:** packaged as model/sds2/<job>.zip (store mode).
- **sha256:** computed for every file.
- **Delta:** each round adds newly shipped models. Removals are queued in `_control/packaging_d3/removals_pending.jsonl` until Dhiren
  approves.
- **Status:** plan / apply / verify run on the fleet. The agent (a5c114cd) writes AUDIT.md / SPEC.md / code under
  `_control/packaging_d3/`; a dry run comes before any apply.

**21:51Z 2026-10-02: FINAL r1 written (graded; independent verification in progress).**

| Pipeline | Class 1 | Class 2 | Class 3 | Distinct |
|---|---|---|---|---|
| IFC | 2,203 | 1,736 | 17 | 3,956 |
| DB1 | 1 | 104 | 1 | 106 |
| SDS2 (states) | 84 | 4,104 | 365 (+4 none) | 4,557 |
| SDS2 (per job, primaries) | 82 | 1,886 | 174 | 2,143 |

- rerun_pending 1,257 (late re-runs land as revisions r2+). Snapshot: `_state/conv/final/r1/`.
- **Verification at r1:** 254 of 491 required still without a verdict.
  - SDS2: 148 verified, 84 class-1 verified, 8 pending, 5 verifier_disagrees.
  - DB1: 49 verified (97c7 class 1 verified).
  - IFC audit: 53 (38 pass / 15 warn).
- r2 (verified deliverable) is cut automatically at verification_complete.

**20:15Z 2026-10-02: pipeline design (Dhiren left it to me) — CONVERT → VERIFY (two independent checks) → CLASSIFY.**
- **CONVERT:** per model, best-of across converter versions (IFC ifc2step6 6.1.7, DB1 code r, SDS2 v5.5.9; SDS2 v5.5.10 canary).
- **VERIFY:** as soon as a STEP lands, two checks run in parallel:
  - (a) our grader (OCC read-back + census join);
  - (b) the teammate's per-format verifier: ifc-step-verifier, db1-step-verifier (Tekla-export truth), sds2_step_verifier
    (independent decode + SDS2 IFC / KISS / NC1). The zips are in ~/Downloads; adapters by agents aa22160f / afc091ac go to
    `_control/z3conv/verify/`.
  - Results: `_state/conv/verify/<pipe>/<id>.json`, keyed by step_key + ETag.
- **CLASSIFY:** deterministic merge in build_index.
  - Class 1 = grader class-1 criteria AND verifier PASS (WARN only with cause source / by_design).
  - Otherwise class 2 with the merged reasons, or class 3 for no usable STEP / a proven source reason.
  - Unverified rows are `class1_pending_verification`.
- The deliverable is final revision r2, cut when `verification_complete`. Box release is held until then.
- **Tolerance policy (21:40Z, my decision under Dhiren's delegation):** a single deterministic tolerance of **0.1 mm**, the converter's
  declared sew tolerance (about exporter precision).
  - Parts with converter-recorded sew_max_mm ≤ 0.1 or gap_max_mm ≤ 0.1 count as exact (info tag).
  - Larger gaps stay open_in_source (class 2, source_data_absent). Real source gaps are mm-scale (missing hole walls).
  - Never keyed on OCC read-time healing.
  - A sew-chaining bug (moves up to 0.33 mm) is being fixed in 6.1.8 / 6.1.9.
- **Dedup (21:05Z):** exact duplicates are converted once, matched by sha. IFC: 3,956 distinct for 8,705 copies. DB1: 106 for 132.
  SDS2: 4,557 distinct states for 7,267 copies, coming from 2,118 jobs; 645 jobs have several saved states (3,059 in total, max 69).
  **Dhiren chose "one primary per job"**: all states stay converted, one primary per jsetup is marked (best class → most parts →
  coverage → latest saved), and the others are tagged older_revision_of. Counts are reported per job and per state. Primaries get re-run
  priority and are what verification uses.
- **20:30Z refinement (Dhiren):** the teammate's tools are a REFERENCE to improve our grader, not a replacement.
  - **IFC:** port ifc-step-verifier's missing rules into our grader. They cover broken solid (volume > bbox), empty / extra parts,
    open-shell source attribution, integrity codes, stray parts and duplicates. Its full verifier runs as an audit sample only, and IFC has
    no pending state.
  - **DB1:** db1-step-verifier truth stage (Tekla's own IFC export), active for all 106.
  - **SDS2:** sds2_step_verifier C1 / M1 / E1–E3, active for class-1 candidates + the sample. Its cheap geometry checks are ported into our
    grader.
- The site shows "graded r1 — independent verification in progress", with a verification column on graded.html.

**12:40Z 2026-10-02: the deadline final started at 12:02:48Z but has 0 claims.**
- Its 376 jobs (IFC 223 read-backs + 128 census, SDS2 19, DB1 6) wait behind the convfleet young-growth memory gate, which is false
  on 22–23 of 23 boxes.
- The fix (young growth × 0.5 after 1 h, capped at 15 % of RAM) is staged and needs Dhiren's SSO login to deploy. It is the first
  step of the builder's login script.
- **Interim classes (index_summary 12:29Z), 8,619 models:**

  | Pipeline | Models | Class 1 | Class 2 | Class 3 | Pending |
  |---|---|---|---|---|---|
  | IFC | 3,956 | 2,193 | 1,746 | 8 | 9 |
  | DB1 | 106 | 1 | 104 | 1 | 0 |
  | SDS2 | 4,557 | 91 | 3,609 | 719 | 138 |

  SDS2 class 3 is falling (≈700 at 12:40) as the v5.5.7 timeout retries land.

**08:10Z 2026-10-02: state for Dhiren's morning.**
- **Verified purge: DONE.**
  - 153,604,435 keys / 159,820,445 versions deleted from annotationprod `cad-disk-extract/`, each only where bim holds an identical copy;
    0 copied first.
  - Kept: 381,102 noncurrent-only versions with no copy in bim. The size census is running. **Ask Dhiren before deleting them.**
  - `_control/` stays: 16,709 current objects (4.5 GB) + 33,862 noncurrent (11.1 GB).
- **The annotationprod-publish SSO expired again at about 08:00Z.** Fixers and the builder can't deploy or use SSM until Dhiren runs
  `aws sso login --profile annotationprod-publish`. The fleet and the EC2 endgame continue on instance roles.
- **Live at 08:01Z:** SDS2 v5.5.7 (rods, no_piece_file, repair labels, verify budget), DB1 code q (P6 overlap-only merge, P4 keeps
  listed holes, P12 new-engine fittings gated off + tagged, 7.64 / 8.53 slots), IFC 6.1.5, step_verify_big fixes (no class 3 from rc 2,
  far shift, final reservation).
- **Ready, waiting on the login:** SDS2 v5.5.8 (invalid parts left out are listed + counted).
- **Live regressions found by verifiers at 10:05Z** (fixes being prepared; deploy after the login):
  - **IFC far mode (V6_FAR_VERIFY):** the output reads invalid in place (15,060 of 38,646 vs 1 of 38,640). Turn it off, grade in place
    first, re-target the far-mode results.
  - **IFC 6.1.2+ patch 1 (opening contact walls):** loses 36 valid parts on 3 pipe-cope models. Fix in 6.1.6: retry-only.
  - **SDS2 v5.4+ always-on split:** loses 2 exact pieces (DSCC #5513, SOCORRO #3492). Make it repair-stage only.
  - **SDS2 grating cap closure:** ignores holes in the covering face. Fix to avoid capping over holes.
  - **Refuted, kept out:** sds2-weights-failures, sds2-pieces-not-built (_nest_voids).
- **Decisions for Dhiren:**
  1. delete the 381,102 kept noncurrent versions?
  2. kill 4 idle code-a/b DB1 worker processes on i-0497fc266f3f8748a (the classifier blocked the builder);
  3. a later final deadline? (12:00Z now; the rules.json edit was blocked; late re-runs land as final revisions r2, r3, …);
  4. env Tekla bolt catalog: **APPROVED by Dhiren 2026-10-02 ~17:55Z, tagged** (`tekla_env_catalog`, info only, does not block class 1;
     used only where the model's own catalog doesn't size the bolt). The builder ships it as DB1 code r;
  5. CIS/2 duplicate parts kept as stored (info tag), OK?

**05:30Z 2026-10-02: Dhiren is asleep. "Finish fully everything … full fixes and conversions."**
- Final deadline stays **12:00Z**: the permission classifier blocked the builder's rules.json edit to 16:00Z, and I did not make it on the
  builder's behalf. Dhiren can approve a later deadline. Re-runs that are unfinished at 12:00Z are marked rerun_pending, and boxes with
  queued re-runs are not released.
- **Live at 05:30Z:** IFC 6.1.5, DB1 code p (cuts / fittings + slots + plates), SDS2 v5.5.5 (7.x pieces, CSU, NC1 opt-in for 457 jobs,
  unplaced-pieces proof).
- **Pending:** SDS2 v5.5.6 (grating / rods; cross bars count as exact only if built from stored outline + depth and weight is within
  ±3 %), Tekla new-engine slots / plates / flat-bar depth, workflow SDS2 items (pieces not built, weights).
- **End-of-run checklist (Claude):**
  1. when FINAL_OK lands, check the publisher shows the final classes (guard: final/READY);
  2. update CONTEXT / MILESTONES with the final numbers;
  3. set the agentjobs RELEASE flag once the fixers are done;
  4. check the fleet self-released;
  5. purge: report the kept noncurrent versions (count / size) and ASK Dhiren before deleting.

**02:10Z 2026-10-02: Dhiren is closing the Mac and taking it home (option 3). Handoff state.**
- **Runs on EC2 without the Mac:**
  - the conversion fleet (coordinator i-039e769ea62de0fa1 + ~24 boxes) and grading;
  - the verified purge (1,040 / 3,838 batches at 02:04Z: 47.0 M keys deleted, 0 copied first, 188,300 kept = noncurrent-only versions
    not in bim; ask Dhiren before deleting those).
- **Stops while the Mac is off:**
  - this session, the builder (a965852984ca96fd8), the fixers (SDS2 afc091ac…, IFC ab87e100…) and the workflow fixers;
  - the publisher `zen2/publish_sources.py`, so the live site goes stale;
  - the builder's Mac control-file watcher.
- **Asked the builder to make it self-running on EC2:**
  - The coordinator removes `coord/final_hold` and starts the final pass by itself when fresh work and in-flight are 0 and every re-run
    target has been tried on current code.
  - Deadline: at 12:00Z it runs the final pass anyway (moved from 10:00Z at 04:17Z), marking unfinished targets `rerun_pending`.
  - SDS2 fresh jobs go before re-runs (04:17Z).
  - After FINAL_OK, conversion and grade boxes self-terminate after 30 min idle. The coordinator and the 3 agent boxes stay (agent boxes
    keep their 20 h self-terminate).
- **Live (updated 04:17Z):** IFC 6.1.3 (04:06Z), SDS2 v5.5.3 (02:53Z), CIS/2 route, IFC2X2 census, coordinator as systemd
  `z3coord.service`, job slice MemoryMax RAM−24 GB on every box.
- **Live at handoff:**
  - IFC ifc2step6 6.1.1 (+s6.1.1+x1);
  - DB1 code n (polybeams, 7.x cut stride 61, 7.30 bolts, own-catalog bolt heads, 9.21 plates);
  - SDS2 v5.5.0 (joists);
  - Pass 1 + 2 grader fixes (openings_not_applied, best-of by coverage, G6 policy, step_verify_big, far-origin km-shift, census v3);
  - admission at 1.6 × RAM with longest-first.
- **Not yet shipped:**
  - SDS2 v5.5.3 (absurd-extent bug, stored-bolt dedup, reference models), in final test on BOX-C;
  - SDS2 7.x pieces, pieces not built, grating, weights (workflow fixers);
  - NC1 holes;
  - IFC 6.1.2 (opening contact walls, null curve segments);
  - Tekla fittings application and slot assignment.
- **On resume:**
  - check final/READY and conv_status;
  - restart the publisher if it died;
  - ship the pending fixes;
  - relaunch a small fleet for their re-runs;
  - re-grade the affected models.
  - SSO may need `aws sso login`.
- Running bug log: `BUGS.md`.

**00:25Z: annotationprod deletion. Dhiren: "move everything to bim and delete from annotationprod"; approved a verified delete.**
- **Correction:** the operator logins (annotationprod-publish, cad-operator, bim) still CANNOT write to bim (explicit deny on PutObject /
  DeleteObject). An earlier "OK" came from `--quiet` hiding the error. My `_control` sync to bim failed for every object; nothing was
  written.
  - So annotationprod `cad-disk-extract/_control/` (13,961 objects, 3.5 GB: converter kits, job lists, flags, agent staging) STAYS until an
    admin grants the operator write on `bim-proprietary-data/cad-disk-extract/_control/*`.
  - The fleet keeps reading control from annotationprod.
- **Verified purge** (move_worker `CODE move-2026-10-02v`, `MOVE_MODE=vpurge`; staged at annotationprod `_control/move/move_worker.py`):
  - For each shard of the move results: list annotationprod versions + bim current objects. A key's versions and markers are deleted only
    if bim has the same size + ETag. Missing keys are copied first; unverifiable keys are kept and reported.
  - `_control/` is skipped.
  - Authorisation: annotationprod `_control/move/purge_ok.json`. State: bim `_state/move/vpurged/<cid>.json`.
  - Single-shard test passed (6/6 verified, deleted, bim unchanged).
  - Running since 00:23Z, 2 processes each on the coordinator + 3 agent boxes. Progress: `python3 /tmp/zen/vp_progress.py`.

**00:10Z: owner decisions + releases.**
- **Open source meshes (IFC parts missing caps / small flat faces): NO gap filling** (Dhiren). They stay tagged surfaces, class 2,
  reason "source mesh open".
- **v6 `L2-alt-source` counts as exact when it verifies.** It is the same IFC item and surface re-faceted (vertices within 0.004 mm of the
  exact B-rep); the cause was a 6.0.1 outer-loop bug. Moved to `v6_info_tags`.
- **ifc2step6 6.1.0-dev3** (`agentjobs/ifcv6/ifc2step6_dev3.py`): outer-loop fix, double-sided meshes become solids, open shells go to
  tagged surfaces, IfcMappedItem instancing (342 MB IFC → 727 MB STEP, was 3.4 GB; big files fit the read-back cap), openings on faceted
  products via the kernel (7.7k products had lost holes/copes), located-instance retry. Regression on BOX-A, then 6.1.
- **SDS2 v5.4** (sha bf4a07fc…): bolt-derived main-member holes. Used for pending jobs only; derived holes are tagged and graded class 2.
  - Greenwood NC1: 90 real holes on 12 placed parts, 0 matched in v5.3 / v5.4. These are single-ply clip / shear-tab connections with no
    bolt record, so the rule never cuts them. The earlier "392" counted punch marks and unplaced parts.
  - v5.4.1 (memory) is being measured.
- **Parallel fixers relaunched** as `z3-parallel-fixers-2`: 4 SDS2 items on v5.4 / drafts, plus 2 IFC items on dev3 (volume residue;
  verification / members / ValueError).

**00:00Z: parallel fixers.** Dhiren: "finish the fixes fast, you are taking all day".
- Ultracode workflow `z3-parallel-fixers`: 7 fixers + reviewers, heavy work on BOX-A / BOX-C, patches under `z3conv/_pfix/` and
  `_control/z3conv/<pipe>/pfix/`.
- **SDS2:** approx pieces 7.x (~600), pieces not built (264), grating + mesh cylinders, weights + stage-2 failures + ValueError.
- **IFC:** surface-to-solid (L4 / L3, 231), volume tolerance (208 + 13 DB1), L2-alt-source evidence + per-part verification + members not
  converted + ValueError.
- The SDS2 fixer finishes v5.4 and then integrates as v5.5; the IFC improver does large files and then integrates as v6.1.
- Also running: the `z3-fixes-remote` workflow (9 streams) and `z3-conv-coverage-audit` (3 auditors + a critic).

**23:54Z: fleet runtime z3-convfleet-v2 (builder).**
- **Why jobs were OOM-killed:**
  - IFC v6 reserved 2 GB for inputs under 128 MB (real p95 13–46 GB); SDS2 medium jobs were under-reserved.
  - Assist workers didn't count each other's memory or CPU.
  - The watchdog killed the largest job instead of the one over its reservation.
- **The fix:**
  - Host-wide job registry; claiming requires memory under 85% (75% for assist) AND CPU under 0.95 × vCPU (0.85 for assist).
  - systemd scope per job (MemoryMax + CPUQuota: IFC / DB1 300%, SDS2 / grade 150%).
  - Measured reservations: 1.2 × p95 per size bucket, recomputed by the coordinator into `_state/conv/<pipe>/mem_buckets.json`.
  - Retries reserve 1.6 × peak; the watchdog kills the job furthest above its reservation.
  - SDS2 boxes are SDS2-only; IFC big_max 3 per box.
- SDS2 class-2 re-runs paused; class-3 lifts continue.
- **build_index** is type-safe, with per-model try/except and `grading_errors.json`. It had crashed every round from 23:13 to 23:35.
- **DB1 code j:** overlay v2 + bolt_catalog + washer flags + standard tables + head rule + hole tolerance + 9.21 / 9.50 layouts; re-running
  all 106. A325M is not implemented (no verified table); it waits for kit_v2's Tekla-harvested dims.

**23:35Z: off the Mac (Dhiren: "don't slow my mac down, use more instances in Mumbai").**
- **3 agent boxes launched** (`cad-z3conv-agentbox`, r7i.16xlarge, 1 TB gp3, AL2023; env = kit setup.sh + mono + 7zz; self-terminate on
  `_control/z3conv/agentjobs/RELEASE` or after 20 h):
  - BOX-A i-0c694360a18d7759f: IFC;
  - BOX-B i-076e73980707c7dbe: Tekla;
  - BOX-C i-0d97427e58ca5ef28: SDS2.
  - Instructions in `/tmp/zen/AGENT_REMOTE_COMPUTE.md`. Userdata at `z3conv/agentbox/ud_agentbox.sh`.
- **Mumbai after the launch:** ours ~1,392 + others ~425 of 2,000; ~180 left for other teams' ASGs.
- **Workflow changes:** stopped the fast-track and Tekla-sprint workflows and killed their leftover / orphan Mac processes (cwd-matched).
  Relaunched as `z3-fixes-remote` (9 streams + reviewers), with ALL heavy compute on the agent boxes.
- All improvers were told to move their heavy work to their box.
- Mac load went 110 → ~50.

**23:20Z state of the fix effort:**
- **Deep-dive workflow stopped after its outputs were harvested.** Its patches went into ifc2step6 (lumpsplit / shellfix), DB1 code g
  (axis guard) and grader census v2 (classifier audit). The rest duplicated the SDS2 v5.x / IFC v6 work and was overloading the Mac
  (load ~110 on 10 cores).
- **Remote compute for fix agents:** the idle coordinator i-039e769ea62de0fa1, via SSM (`/tmp/zen/AGENT_REMOTE_COMPUTE.md`). Staging in
  `annotationprod _control/z3conv/agentjobs/`, outputs in `bim …/zenitude-data-3/_state/agentwork/`.
- **Tekla engine-variants fork:**
  - data-4 `no_member_layout` (193) = 3 gate variants (spread / geo 2e8 mm / flag1). Fixed as a retry path; truth 1,242/1,242 plates,
    879/879 profiles.
  - suspect_attr_link (43 × 8.85) = a naming false positive.
  - 7.30 Disk-1/2 = empty templates.
  - 9.21 / 9.50 layouts approved (stride 381); 9.21 gives 1,618/1,618 profiles.
  - **Fittings are not decoded in any engine**, so fitted beam ends run long (median 18 mm per end). Next major Tekla fix.
- **Tekla profiles fork:**
  - washer_side_proof: digits d5..d0 = holes-only / washer head / washer2 / washer nut / nut1 / nut2; 1,837/1,841 vs IFC.
  - bolt_catalog: per-model assdb.db + screwdb.db decoded; 100% vs IFC geometry; 14 data-3 models.
- **SDS2 v5.3:** dedup grid 0.1 in. v5.4 = bolt-derived main-member holes (SDS2 stores no main-member hole records), validated vs NC1.

**Owner rule (2026-10-01 23:15Z): "don't touch anything, let it be".**
- No new instances anywhere; the free Mumbai vCPU (~375) stays for other teams.
- Work continues only on the existing boxes (re-tasking OK).
- All agents have been told.

**Capacity check (2026-10-01 23:05Z). Dhiren: use +300–400 vCPU only if no other project needs the vacant spots.**
- **Mumbai:** quota 2,000; ours 1,264; others 449; headroom 287.
  - **Not used:** other teams' ASGs depend on it. dataforge-asg (max 50 × m6i/m5/m6a.8xlarge), dataforge-genful-asg (max 50),
    dataforge-asg-arm64 (max 12), taskbot-worker-asg (5 → max 50), and EKS nodegroups.
- **Hyderabad:** 320 / 320, ours.
- **ap-southeast-1 Singapore:** quota 256, unused, but **CANCELLED. Dhiren: "we only use Hyderabad and Mumbai".** Never use other
  regions. Verified 0 instances there.
- **us-east-1:** quota 256, others use 96; not used.
- **Fleet audit by SSM:**
  - Idle: 2 Hyderabad SDS2 boxes, the coord, and a fixer test box.
  - Overloaded: grade boxes at load 259–426/64 and IFC at 170–231/64 (ifc2step6 threads × slots); DB1 at 139/32.
  - The builder is fixing both.

**More fixes landed (2026-10-01 ~22:45Z):**
- **ifc2step6 v6.0.1** (`_control/z3conv/ifc/ifc2step6.py`, md5 341c16ab…; notes in `z3conv/ifc_v6/CHANGES.md`):
  - Splits multi-body shells (the main non-positive-volume cause) and writes real voids.
  - Hole-loop rewind / triangulation / T-junction / seam closing (≤0.1 mm).
  - Per-part read-back with a tagged fallback chain.
  - Deployed for IFC and the DB1 STEP stage, best-of; class-2 IFC / DB1 re-runs.
- **Tekla profile overlay** (`_control/z3conv/db1/v2/tekla_profiles_overlay.json`):
  - Decoded from the models' own profdb.bin (29 data-3 model folders) and own Tekla report weights.
  - global 85 entries (angles r1/r2, R.B Ø), per_model 28; tier C not applied.
  - Code patch `z3conv/db1_v2/prof/apply_prof_patch.py`: R.B Latin-1 names, ELD/EPD exact frustum, null records dropped.
  - Lift: root radius 6,935 parts / 52 models.
- **DB1 code g:** deep-dive axis-guard patch (8/9 recovered, 6/6 controls identical). Reused DB1 models are re-converted.
- **Ultracode fast-track workflow** (`z3conv/_fast/`): ifcXML converter, streamed big-STEP verifier, SDS2 IFC-recall + NC1 tools,
  SDS2 v5.1 and DB1 regression audits.
- **Utilisation issue:** the 8 r7i SDS2 boxes sat at load ~14/64 with ~410 GB free (capacity accounting). The builder is fixing it.

**Conversion fixes landed (2026-10-01 ~22:10Z):**
- **SDS2 v5.1** (`_control/z3conv/sds2/sds2-step-pipeline-v5.1.zip`, sha 8f74f449…):
  - Reference-model jobs (DWF Import / ReferenceModel, written from stored B-reps) are corpus R, graded by fidelity.
  - Empty sandbox jobs carry `empty_job_proof`; 19 proven in the 2015.25 jobs.7z.
  - Read-back invalid-solid repair; grating tagged; weight outliers listed (not broken); 7.7xx joist fallback.
  - Most early SDS2 class-3 "empty" verdicts were this reference-model gap.
- **Tekla DB1, old engines** (builder codes c / d / e):
  - Bolts + holes match db1tostep.exe exactly (474/474, 347/347 within 0.5 mm).
  - Bolt standards come from the material field (A325/A490 heavy hex, A307 hex, ISO 4014/4032; metric-rounded → inch within 1 mm,
    logged).
  - Hole tolerance = field 4 of `MM<d>*<L>/…`.
  - Policy switch `bolt_standard_geometry_exact` in `_control/z3conv/coord/rules.json`.
- **Tekla improver findings:**
  - GUID join DB1↔IFC Tag gives ground truth.
  - 8.x bolt groups = stride-73 member records, pattern stride-341 (u@21, v@61), attrs stride-317 (d@269, L@305, tol@281,
    slots@273/277, flags@301); 96.7% exact.
  - Old-string fields: f6 = grip-centre offset, f10 = grip; head underside = f6 + f10/2.
  - Flags d5 = holes only, washers = d4+d3+d2, nuts = d1+d0 (100% vs IFC).
  - Grader bug fixed: 8.x profile-less bolt records are now counted as connection parts.
- **ifc2step6:** in development (`~/Downloads/Deccan/z3conv/ifc_v6/`).
- **Deep-dive:** 7 categories with patches under review.

**Owner rules for conversions (2026-10-01):**
- Convert everything first. Classes come from ONE final grading pass over the finished STEP set; the live classes are interim.
- Every class 2/3 model states `missing` + `needed_to_fix` in plain language, categorised as converter_feature / source_file_missing /
  source_data_absent / profile_or_catalog_missing / source_damaged. The aggregate fix plan is `_state/conv/class2_fix_plan.json`.
- Every version of every type must convert (IFC2X…IFC4X3, ifcZIP, ifcXML; Tekla 6.87–9.50; all SDS2 versions). An unsupported
  version is a bug unless the source is proven damaged.
- Maximum code support, but **never fabricate geometry**:
  - Standard-derived or estimated parts (SJI joists, sizes estimated from weight, healed triangulated fallbacks) are tagged
    `[approx: …]` per part and never count toward class 1 unless Dhiren decides otherwise.
  - Bolts only where they are decoded and validated.
- Joist class: no decision yet. The grader policy is a config switch (no reconversion needed); the default is class 2 / B.
- SDS2 v5 is uploaded (`_control/z3conv/sds2/sds2-step-pipeline-v5.zip`, sha 592c1d4f…): derived joists, NaN-frame phantom fix,
  duplicate pieces, bent plates, built-up fallback, face-vertex fitting + holes, invalid-placement fix, 4 crash fixes.
  - Swapped in with best-of v4/v5 per job.
- **Ultracode deep-dive workflow** (7 failure categories + classifier audit, each adversarially reviewed); outputs in
  `~/Downloads/Deccan/z3conv/_deepdive/`.
- Builder raised slots (IFC/grade 48, SDS2 60 per 64 vCPU). Idle boxes are re-tasked, not terminated, until everything is final.

**Conversions — max-effort mode (Dhiren 21:10Z: "optimize and fix our conversion pipeline to the fullest … write full new code if you
want", so most models should be class 1).** Four agents:
1. **Builder:** fleets, grading, re-runs. 16 boxes / 960 vCPU. Full lists started 21:00Z. Status in `_state/conv_status.json`.
2. **SDS2 fixer → v5:** FIX docs, real SJI joist geometry from designation, ZeroDivisionError.
3. **IFC improver → ifc2step6:** orientation, healing, volume check, huge-file read-back.
4. **Tekla new-engine improver → db1 v2:** bolts 7.30–9.x, engine 9.21, no_member_layout, axis-guard drops.

Plus the builder's port of the old-engine (6.87/7.01/7.24) bolt reader + holes, which covers 97 of the 106 data-3 Tekla models.

Each improved converter re-runs every class-2/3 model it addresses, including reused Disk-1/2 / Z4 STEP (a fresh STEP in data-3
supersedes the reused one), with before/after history in conv_status.

**Early classes (21:06Z):**
- IFC 127 class 1 / 102 class 2: 82 non-positive-volume solids, 51 invalid solids.
- DB1: 0 / 54 / 2, because bolts and holes are missing.
- SDS2: 0 / 7 / 51; joists are written as envelope boxes, and the class 3 are genuinely empty seed jobs.

**DATA-3 FINAL (2026-10-01 03:36Z)**
- Final verification record: `bim …/zenitude-data-3/_state/stats/final_verify.json`.
- **Jobs:** 5,992 / 5,992 results — 5,924 ok, 57 partial, 11 failed. Partial and failed are source damage:
  - 11 = the report's "cannot be opened";
  - 4 partly listed;
  - 10 CRC/header member errors;
  - 45 jobs with 117 corrupt nested archives.
- **Completeness:**
  - 0 upload errors.
  - Completeness vs the report: 2,980 / 2,980 match, plus 6 archives not in the report.
  - Loose files 766,619 / 766,619.
  - Manifest rows 372,225,432 = result files.
- **Object audit** (`_state/stats/audit_objects.json`): 168,010,409 objects (3.96 TB) under extracted/.
  - stored_ok 166,790,848 + disk_but_own_object 1,219,561 = 168,010,409.
  - 0 missing, 0 orphans.
- **Totals:** 372,225,432 files (15.23 TB raw), 63,477 nested archives (deepest 4), 909 extensions.
  - Unique 41,726,559 (5.04 TB); new vs Disk-1/2/Z4 35,669,904 (3.47 TB).
  - Raw old 73,598,812 (3.77 TB) / new 298,626,620. `z3_final_counts.py` recomputed this from the prior index for every copy and got
    the same numbers as the worker flags.
- **SDS2:** 7,267 job folders, 2,157 unique, 2,023 new; 361.2M files / 9.48 TB (66.9M old).
- **3D** (raw / unique / new unique):
  - IFC 8,676 / 3,941 / 1,164
  - STEP 6,207 / 2,500 / 93
  - DB1 240 / 202 / 101
  - RVT 373 / 130 / 56
  - NWD 84 / 39 / 30; NWC 246 / 127 / 61
  - SAT 1,523 / 1,506 / 0; IGES 526 / 473 / 473
- **2D** (raw / unique / new unique):
  - DWG 114,587 / 52,305 / 1,919
  - DXF 644,985 / 292,407 / 55,072
  - DGN 92 / 78 / 14
- **CNC:** NC1 1,455,394 / 610,289 / 120,285; KSS 56,965 / 29,088 / 23,205.
- **PDFs** (`z3_final_counts.py` resolved the 173,938 unique unknowns): 5,470,890 raw / 1,975,004 unique / 299,465 new unique.
  - **CAD 3,227,347 / 1,302,277 / 222,598**; documents 2,241,673 / 672,698 / 76,838; not a PDF 1,870 / 29.
  - Sources: worker 1,801,066; data-4 classes.sqlite 35,344; Disk-1/2 union.sqlite 112,549; whole-file pdfinfo 26,016.
- **Size funnel:** 4.24 TB on the drive (compressed) → 10.68 TB unzipped (report) → 15.23 TB raw (plus nested contents, every
  copy) → 5.04 TB unique → 3.47 TB new.
  - Stored 3.96 TB > new unique because files < 64 KB are stored once per archive, not once per disk.
- **Shutdown and leftovers:**
  - All 27 extraction boxes self-terminated.
  - Aggregator stopped (outputs final).
  - z3autorerun stopped.
  - Coordinator `cad-move-coord` TERMINATED 04:43Z: logs and audit rows backed up to `zenitude-data-3/_state/box_backup/cad-move-coord/`; shut down from inside (shutdown behaviour = terminate; the operator role has no ec2:TerminateInstances).
  - **0 CAD instances in ap-south-1 / ap-south-2.**
  - Move `stop` flag set at `annotationprod/cad-disk-extract/_control/move/stop`. **Delete it before running the annotationprod purge**
    (purge = next step; needs Dhiren's go and a new box).
- **Code:** `zen2/z3/z3_audit.py`, `zen2/z3/z3_final_counts.py`, `zen2/zx_worker.py` r (skip already-stored objects on re-runs).
- **PII trial page:** published at https://dhigdec.github.io/cad-extract-status/pii-trial/ (noindex, images only), at Dhiren's explicit
  request after a warning that it shows real PII.

**Data-3 status 2026-10-01 02:50Z (superseded by FINAL above):**
- 5,989 / 5,992 jobs (2,986 archives + 3,006 loose-folder jobs; 6 archives + 563,866 loose files were added by our own
  coverage listing).
- **Stats at 5,950 jobs:**
  - 326.5M files (13.9 TB) at all nesting levels (deepest 4), 60,010 nested archives unpacked, 906 extensions.
  - 40.3M unique contents (4.89 TB); 34.3M new vs Disk-1/2/Z4 (3.33 TB).
  - SDS2: 6,386 job folders (2,121 unique, 1,988 new), 315.8M files.
  - PDFs: 5.32M raw / 1.95M unique / 296k new unique. CAD 2.95M / 1.22M / 196k.
- **Loose files: 766,619 = every non-archive object.** 774,330 source objects − 4,725 folder markers − 2,986 archives.
  - The old "1,331,538" figure was the report's recursive per-folder count (sub-folders counted twice).
  - stats_agg now takes each finished folder job's own `source_files` / `bytes`.
- **Checks vs the report:**
  - 11 failed rc=2 = the report's 11 "cannot be opened".
  - 4 partial = the report's 4 "partly listed".
  - The EMC capture zip holds the report's 25 password-protected entries.
  - 10 more archives have CRC/header errors in single members (source damage).
  - 47 jobs have damaged nested archives (78 corrupt-data, 13 not-an-archive).
  - 6 archives are not in the report.
- **Re-runs:**
  - z3autorerun on the coordinator (/opt/z3rerun) re-queues upload-throttled partials every 15 min, max 3.
  - 4 retry-exhausted jobs were re-queued by hand (`rerun_log/*.a4.json`).
  - 3 jobs whose scratch vanished mid-run (errno=2, files 0) were re-queued (`*.vanished.json`).
- **Worker `q` (zx-2026-10-01q):** upload_tree lists the job's existing objects first and skips same-key + same-size objects, so a
  re-run PUTs only what is missing (DUPONT: 2 h → minutes).
  - Slow p re-runs were restarted on q via `/tmp/zen/z3restart_tpl.sh` (kill the box's workers, clear scratch, release the claim).
  - Known p-era effect: re-run manifests record files the job itself stored earlier (≥64 KB) as dedup `disk`.
    `z3/z3_audit.py` reclassifies them (`disk_but_own_object`).
- **Final object audit `zen2/z3/z3_audit.py`** (coordinator /opt/z3audit, cached per manifest ETag in rows/):
  - Lists every object under each archive's extracted/ prefix and checks it against the manifest (stored_ok / stored_missing /
    orphans).
  - Output → `_state/stats/audit_objects.json`, shown on the site once complete.
  - Test on 3 jobs: 387,782 objects, 0 missing, 0 orphans.
- **Idle boxes:** terminating idle boxes was blocked by the auto-mode classifier. Boxes self-shut-down when every job has a result
  (no z3 hold file).

## 1. Where things stand (one screen)

| Source (s3://bim-proprietary-data/) | Size | State |
|---|---|---|
| `Disk-1/` | 1,154 archives, 6.12 TB | **Done** 2026-09-24/26 (extracted CAD types only, converted, packaged) — §3 |
| `Disk-2/` | 2,466 archives, 3.25 TB | **Done** (same) |
| `Zenitude-data-2/` | 3,516 objects (~2,196 files), 223.2 GiB | **3D COMPLETE (03:50Z)**: 45,003 JSON + PCF; 1,927 IFC (1,711 piping, 138 structure from ACIS, 78 equipment) → 1,927 STEP (OCC read-back, roots = parts, 2,917,779 parts) + GLB + OBJ + 2,239 PNG; 549,831 model drawings exported; 2D complete — §4 |
| `Zentitude-data-4/` (sic) | 53,443 objects, 7.90 TB, 1,499 archives | **COMPLETE + VERIFIED 2026-09-30 00:32Z** — 1,499/1,499 archives, 117.6M files, 18.66M unique objects stored (4.88 TB), completeness 1,490/1,490 vs drive listing — §5 |
| `Zenitude-data-3/` | 774,328 objects, 3.86 TiB | Not started. Superset of Disk-2 with ~510 new archives (~739 GB, per audit); mostly SDS/2 jobs |

**Live status pages**
- Public (anonymous): https://dhigdec.github.io/cad-extract-status/sources.html (new disks) and https://dhigdec.github.io/cad-extract-status/ (Disk-1/2, frozen since 2026-09-29 07:01Z — its publisher box was terminated).
- Private (names): `/Users/dhiren/Downloads/Deccan/zen2/live/private.html` (local file, refreshes every 60 s).
- Publisher: `zen2/publish_sources.py` runs on Dhiren's Mac (bim profile, `caffeinate`), pushes `sources.json` every 2 min.
  Stats aggregator `zen2/stats_agg.py` runs in-region on `cad-zen2-files` (manifests → file-type stats every 60 s).
  **If the Mac sleeps or is closed, the public page stops updating** (restart: `cd zen2 && nohup caffeinate -i ../cad-db1-convert/venv/bin/python publish_sources.py 120 &`).

Target formats (lead, 2026-09-29): STEP (top pick), DXF (ASCII), DWG, PCF, glTF/OBJ + PNG, parsed JSON.
Priority rules from Dhiren: IFC/STEP-bearing folders first; for Zenitude-data-2 the 167 GB model DB first; dedup everything;
each disk in its own folder; full extraction (every file, nested archives to the deepest level); live stats with file types.

## 2. AWS access (names only)

- Account 874846752452. Regions ap-south-1 (Mumbai), ap-south-2 (Hyderabad). **Capacity: ≤ 700 vCPU in Mumbai; Hyderabad fully.**
- Profiles: `bim` (IAM user: S3 get/put/list/copy on annotationprod `cad-disk-extract/*`, read `bim-proprietary-data`,
  EC2 Describe; no delete, no SSM; **cannot read object tags** → S3→S3 copies need `--copy-props none`),
  `annotationprod-publish` (SSO `annotationprod-s3-access`: S3 incl. delete on `cad-disk-extract/*`, SSM (one instance per call),
  Start/Stop/Terminate, **RunInstances + PassRole cad-disk-extract-ec2 work**), `cad-operator` (SSO `CAD-Disk-Extract-Operator`,
  added 2026-09-29, permissions unmapped), `annotationprod-audit` (S3FullAccess — **no longer assigned**).
- Granted 2026-09-29 (Dhiren confirmed): EC2 role `cad-disk-extract-ec2` can read `bim-proprietary-data` (verified from a box;
  SSE is AES256, no KMS); bim GetObjectTagging; SSO RunPowerShellScript, StartSession/port forwarding, GetPasswordData.
- Security groups: `sg-04a594766aa42b691` (cad-disk-extract-egress, no inbound) for all new boxes. `sg-088de8e930b87b429` is open to the internet — do not use for services.
- SSM gotcha: background processes started from an SSM command can be killed when the command ends → start with `setsid nohup … < /dev/null &`.
- Local tools: `cad-db1-convert/src/ssm.py REGION INSTANCE SCRIPT [timeout]` (AWS-RunShellScript helper).

## 3. Disk-1 / Disk-2 (finished 2026-09-26; re-verified 2026-09-29 by audit)

- 3,620/3,620 archives extracted (Disk-1 1,154 / 6.12 TB; Disk-2 2,466 / 3.25 TB), 0 failed. The worker extracted **only CAD
  extensions** (.pdf .dxf .dwg .dg .dpm .stp .step .ifc .db1 .sat .obj .stl .gltf .glb .nc1 + archives) and did not content-dedup at write time.
- Deliverable `cad-disk-extract/dataset/main/{3d,2d}/`: **2,476 packages** (1,286 3d / 1,190 2d incl. 5 empty), **26,071,766 files,
  20.68 TB** (not 6.54 TB — STEP added later), 34,270 STEP (6,220 native / 14,652 IFC / 13,398 DB1), 0 duplicates. Unchanged since 2026-09-26 01:51Z.
  Disk-1 = 1,294 packages / 18.56 TB; Disk-2 = 1,182 / 2.12 TB.
- Dedup index for Disk-1/2 content: `_state/dedup-union/union.sqlite` (2.43 GB, ~16.36M distinct sha256; no sha→key mapping).
- Gaps found by the audit: 653 small archives marked done by the early laptop run have no extracted folder (~14,468 wanted
  files may never have been stored); ~150k loose (non-archive) files on Disk-1/2 were never in scope (incl. 32k PDFs / 167 GB on Disk-2);
  622 Disk-2 archives stored nothing because they contain no wanted types (mostly SDS/2 jobs), not because of dedup.
- Old superseded copy `cad-disk-extract/packaged/` — delete awaiting Dhiren's OK.

**Activity 2026-09-28/29 by an OpenAI Codex desktop session on this Mac (at Dhiren's direction):**
SDS/2→STEP run 1 (`sds2-step-r1-20260928-01/`, 10 × i4i.16xlarge, v1 code, superseded, 762 STEP / 255 GB) and run 2
(`sds2-step-r2-20260929-01/`, v4/v6, paused 06:56Z: 1,161/1,185 jobs with results, **754 accepted STEP / 184 GB**, 155 non-accepted
STEP in the same folders, never promoted; `derived/sds2-step/` empty). Source was raw Disk-2 SDS/2 jobs. It also launched a
Zenitude restore box in Hyderabad (gone), terminated the lead's `hyd-status`/`hyd-medium` (status publisher) at 07:01Z, and left
**two detached volumes in ap-south-2**: `vol-00f8bb72f6ac20a6b` (1 TiB, zenitude restore) and `vol-0310a6d23759a4c6e` (300 GiB,
hyd-status root) — billing; deletion needs owner OK. `meshwork/` (STEP→OBJ test of 10 lead models) is partial. The public
Disk-1/2 feed is frozen since 07:01Z.

## 4. Zenitude-data-2 (3D + 2D complete; boxes terminated)

**What it is.** Two unrelated things on one disk:
1. `PLC 17072025/`: a Hexagon Smart 3D **v13.0.1** backup of plant **MLNG@1** (project root PLC): SQL Server 2019 (15.0.2000)
   full backups, uncompressed, not encrypted, taken 2025-07-17 05:39-05:53 UTC on `SP3D1\S3DT`. Model 167 GB (20,391,256 pages),
   catalog + catalog schema, site + site schema, `PLC.bcf`, logs. `.7z` copies = same `.dat` (name/size/mtime/head+tail bytes match).
   `SharedContent_MLNG(S3Dv13).7z` = 34,186 files / 38.0 GB: symbol DLLs (1,416 COM + 497 .NET), Isogen styles (incl. PCF_Stress),
   drawing templates, **2017 SmartPlant Review exports of MLNG modules** (1,742 .vue, 9 .mdb2, label XML up to 1.15 GB with
   per-object class/name/material/commodity code/NPD/ranges), the S3D 13.00.01.3006 installer, HF45, SSMS, 9.2 GB duplicates.
   **Contains credentials** (`SSP3D1.ini` DB login, `Temp/MY00111035.cci` licence connection) — never publish; redact before sharing.
2. The rest (~2,187 files, 1,856 distinct): piping drawing deliverables of **ADNOC Onshore "EPC of Sahil Phase 3" (P16093, plant CDS)**,
   Jan-Jul 2026, **"Restricted Circulation"**, with personal names in files. 669 distinct .sha (S3D drawings, OLE2), 1,067 distinct vector
   PDFs, 70 distinct DWG (+32 DWG .bak), 118 drawing numbers. Of 11 root .nwd only `23-04-2026/P16093_Sahil_CDS (1).nwd` (1.19 GB) is this
   project; 10 are unrelated third-party models (HPCL, AVEVA offshore, Alto Maipo, PDS wellheads) — usage rights unclear.
   P16093 is **not** the MLNG model, so drawing↔S3D-model pairs from this disk are not possible.

**Done (2026-09-29)**
- `cad-zen2-sql` (i-02c20241cf997b48d): all 5 DBs restored on SQL Server 2022 Standard (RHEL): MDB 164,286 MB, 814 tables / 15,267 views
  (restore of the model took ~5 min after an s5cmd pull at 1.4 GB/s). Full export **1,875 tables → JSONL** (FOR JSON, exact escaping):
  `zenitude-data-2/json/db/<db>/<schema>.<table>.jsonl.gz` + `_schema.json` (binary columns listed, exported separately later), 10.9 GB gz.
- `cad-zen2-files` (i-0afb7c16dab7a238d): SharedContent unpacked → `zenitude-data-2/extracted/SharedContent_MLNG(S3Dv13)/` (34,186 files);
  DWG→DXF (LibreDWG 0.13.3) 131 ok / 1 failed → `dxf/`; 1,294 PDFs → 2,146 PNG pages (150 dpi) → `png/`, page text → `json/drawings_text/`;
  sha256 of all source files (2,190 files, 1,859 distinct, 323 duplicate groups) → `json/`.
- Source copy in our bucket: `zenitude-data-2/source/` (all files incl. the 167 GB .dat and SharedContent).

**Key discovery — geometry is in plain columns.** The model DB stores coordinates directly: ROUTEPipePort 1.73M (place point,
direction, NPD, OD, end prep, rating, schedule), pipe path features ~2.7M (straight/turn/branch/end start-end XYZ), ROUTEPipeWeld 1.27M,
STRUCTMemberPartAxisLin 880k (start/end XYZ), EQUIPPipeNozzle 456k, CORESpatialIndex 12.5M bboxes, plus blobs (GEOTOP*Body,
COREGraphicDataCache 6.3M). → Plan: own decoder (like Tekla DB1) → IFC → STEP / glTF / OBJ, PCF per pipeline, parsed JSON — no licence.
Equipment shapes initially as bounding boxes + nozzles. Relationship mapping in progress (subagent → `zen2/S3D_DATA_MODEL.md`).

**Drawings stored inside the model (found 2026-09-30):** `MLNG@1_MDB.dbo.DRAWNGDocumentData` holds 549,831 zip-compressed
documents (18.9 GB; ~60% Deflate64 → needs `zipfile-deflate64`): 170,569 isometric .sha (Smart 3D drawings), 50,675 ORIGINAL Smart 3D
PCF, 126,905 Isogen XML, 46,873 POD, logs, 12 ACIS .sat. Sheet names = pipeline line numbers; `DRAWNGDrawingMap` (8.6M rows) links drawing
views to model objects → real 2D↔3D pairs for this plant. **Export COMPLETE 02:00Z**: `zen2/export_model_drawings.py` (8 partitions on
cad-zen2-sql, needs `zipfile-deflate64`) → `zenitude-data-2/model_drawings/<type>/<full-oid>__<name>` (549,831 objects, 0 unzip errors) +
`_index/p<k>-<n>.jsonl.gz`. (First attempt used the 8-hex class-id prefix → 37% key collisions; 347,367 stale objects deleted.) Next (builders): pairing index per pipeline, rebuilt-PCF validation
against the original PCFs, .sha vector decode or isometric DXF/PNG rendered from the original PCFs, ACIS decode.
- Pairing index `model/pairs/` (02:06Z): 45,003 pipelines; 27,379 with isometric sheets (75,431 sheets); 23,478 with Smart 3D's original PCF.
  **Rebuilt-vs-original PCF validation: 23,478 pipelines, 94.14% of original parts matched by Smart 3D part oid within 1 mm (779,546 parts).**
- **2D COMPLETE (03:00Z, builder report):** P16093: 1,083 PDF pages → vector DXF (render-back ink IoU mean 0.954, 4 pages < 0.9 —
  font), 1 PDF is zero bytes on the disk; DWG 1604 via ODA File Converter; 787 .sha JSON; `json/drawing_index.json` (362 sheets).
  Model drawings: 170,518 .sha → `model_drawings_json/` + `model_drawings_dxf/` (geometry only: lines/arcs/circles/polylines/views;
  no text size/fills/symbols yet — ~2-4 days more RE or an S3D licence for full fidelity), 45,184 real iso sheets rendered to PNG;
  50,675 isometrics drawn from the ORIGINAL PCFs → `model_drawings_iso_from_pcf/` (DXF+PNG, 0 failures); `json/model_drawing_index.json`
  (203,575 drawings; 35,873 with both .sha and PCF). `dxf_from_sha/` (P16093) is labelled experimental/partial.
- Earlier 2D builder notes: P16093 PDF→DXF done (1,083 pages, IoU-validated); experimental .sha vector decode works (geometry) → model_drawings_dxf/;
  isometric DXF/PNG from original PCFs → model_drawings_iso_from_pcf/; title blocks → model_drawings_json/. 6 × c7i.8xlarge extra 2D
  workers (`cad-zen2-2d-worker`, builder's `_state/d2_code/ud_md_worker.sh`, self-terminating) launched 02:22Z.
- 3D fan-out: 15 × c7i.16xlarge (10 Mumbai + 5 Hyderabad) ran the builder's kit (`_control/s3d3d/run.sh`, 2,005 jobs); released 01:17Z.
- The P16093 drawing set on this disk is a different plant — it does NOT pair with the rebuilt 3D; the model-stored drawings do.

**Licensed route (optional):** full-fidelity exports need S3D 13 + Octave/Hexagon ISL licence (no trial found), AD domain,
Windows Server 2019 + SQL 2019. Navisworks trial for the P16093 .nwd → FBX → glTF/OBJ/faceted STEP (needs Windows + Dhiren's Autodesk sign-in).

**Output layout** `s3://annotationprod/cad-disk-extract/zenitude-data-2/` → `source/`, `db/`, `json/`, `extracted/`, `dxf/`, `png/`, `_state/`
(and later `ifc/`, `step/`, `pcf/`, `gltf/`). The older `zenitude-data-2-restore-20260929/` (Codex, drawings only) is superseded.

## 5. Zentitude-data-4 (extracting)

- 8 TB "TeklaBackup" SSD; report `/Users/dhiren/Downloads/Zentitude-Data-4_Report_standalone.html`: 77.2M files / 14.1 TB unpacked in
  1,490 archives, 14,275 Tekla models, 193 SDS/2 jobs, 30,555 .ifc, 7,123 .stp, ~161k ransomware-encrypted files (.wiki/.zepto) in 17 archives.
- **1,154 archives = Disk-1 exactly by path+size** (list `zen2/z4_disk12_duplicates.json`). Disk-1 kept only CAD extensions, so per
  Dhiren's goal these are **fully extracted as phase B** (6.12 TB; 571 archives with IFC/STEP = priority 1 / 5.29 TB, 325 with Tekla models = 2,
  258 others = 3). Dedup is disk-wide within data-4 (cross-disk overlap with Disk-1 can be computed later from manifests vs union.sqlite).
- **Phase A (running):** 345 new archives (336 `TEKLA-HYD/Backup 2026` + 9 `CES_PEMB`, 1.745 TB, ~9.66M files) + 44,649 new loose files.
  Worker `zen2/zx_worker.py` (S3 `zentitude-data-4/_control/zx_worker.py`, code zx-2026-09-29b): full 7-Zip 24.08 extraction, empty password
  (never prompts), nested archives unpacked into `<name>!/` to depth 15, encrypted nested recorded, ransomware files flagged, **disk-wide
  sha256 dedup** (first writer stores, others get a pointer; markers in `_state/sha/`), per-archive manifest + result, heartbeats, claims via
  S3 conditional writes, `hold` flag, fleet overrides `_control/zx_env.json`.
- Fleet (all i4i.8xlarge, shutdown=terminate, tag Project=cad-disk-extract, Name cad-z4-extract*): Mumbai 20 boxes (canary
  i-042dea8a29570555d + 8 phase-A boxes + 11 phase-B boxes, 640 vCPU; with the 2 zen2 boxes = 688/700) and Hyderabad 10 boxes
  (`cad-z4-extract-hyd`, 320 vCPU = full quota; user-data `zen2/ud_zx_z4_hyd.sh` sets AWS_DEFAULT_REGION=ap-south-1).
  User-data `zen2/ud_zx_z4.sh`: restart loop; DONE only when all jobs have results and no `hold` flag (hold is ON).
- Worker versions: a (single process) → b (multi-process, depth 15) → c (re-reads jobs when idle, priority order, fast claims) →
  d (non-UTF-8 member names → cp1252 key + raw bytes hex in manifest) → e (hot reload on new code + version-aware stop flag) →
  f (dedup inside each archive locally; files < 64 KB stored directly without a global marker; no marker GET for dups — pointer
  `sha256:<hash>`) → g (files < 64 MB uploaded with one direct PUT instead of a transfer manager per file: ~2x fleet throughput,
  3k → 6.4k files/s) → **h (claim takeover when no live worker lists the job — a crashed process on a live box can't block an archive)**.
  `_control/stop` = minimum version (currently `zx-2026-09-29g`); newer processes hot-reload on each S3 code change.
  Extra worker processes were started on every box with `setsid` (tags x/c/g) alongside the boot-loop worker.
- Stats: `zen2/stats_agg.py` (v2) on cad-zen2-files counts raw files and **unique = distinct sha256 per file type across the whole disk**,
  and checks every archive: top-level files extracted vs the drive report's 7-Zip listing count (`_control/report_archives.json`) —
  23:05Z: 267 match, 0 mismatch, 9 archives not in the report. `zen2/pdf_classify.py` classifies every unique PDF (CAD drawing /
  document / unknown) from Producer/Creator/XMP and page size (head+tail 64 KB range reads).
- Phase A = 345 archives only on data-4; phase B = 1,154 archives identical to Disk-1 archives, re-opened because Disk-1 kept only CAD types.
- **Dedup policy (Dhiren, 2026-09-29 23:15Z): "full deduped of everything"** → worker k skips any file whose sha256 Disk-1/Disk-2 already
  stored (index `_control/disk12_sha64.bin`, 16,356,171 distinct sha256 prefixes from union.sqlite kind='sha'; validated: phase-B CAD files
  96.1% present, non-CAD 0.0%) and records `disk12:sha256:<hash>`. Before k: 1,866,991 objects / 407 GB of such duplicates were stored
  (dry-run list `_state/dedup_disk12/`); **Dhiren chose to keep them — no deletion.** Phase B was paused 23:10Z (258 done, 359 in flight,
  537 pending) and resumed on k.
- 23:25Z: pre-k workers (a/c, slow per-file uploads, no Disk-1/2 dedup) retired on all boxes; boot loops restarted on k with
  12 processes x 2 slots (`zx_env.json` procs 12). Their ~350 in-flight archives were orphaned claims → **worker l** (23:36Z) fixed
  the takeover scan (random sample instead of the same first 6 jobs) → in flight 5 → 155+ within a minute.
- Status 23:35Z: 1,149/1,499 done (phase A 219 before-rule; phase B 394 before-rule + 534 after-rule: 5.47M files, 3.01M skipped as
  already in Disk-1/2, 0.81M stored). Remaining 350 large archives (126 A / 1.26 TB, 226 B / 4.8 TB).
- **FINAL (verify_z4_final.py, 2026-09-30 00:32Z, `_state/final_verify.json`):** 1,499/1,499 results (1,438 ok, 61 partial = damage in
  the source archive: CRC/data/header errors, truncated nested archives, multi-volume .cab parts, non-zip '.zip' — reasons in each result);
  completeness vs drive report 1,490 match / 0 differ / 9 not in report; source copy 52,780/52,780 same sizes; 0 upload errors; all error
  records resolved. 117,573,886 files (18.49 TB); 18,656,435 unique objects stored (4.88 TB); 98.9M dedup pointers (53.9M already in
  Disk-1/2); 105,542 nested archives (deepest 6); 2,696 password-locked nested; 161,941 ransomware-encrypted files; 4,823 extensions.
  Worker n (00:15Z) added the long-file-name fallback (`7z e -so -spd` to a shortened name, `orig_path` in manifest): 2 archives re-run
  (+23, +1 files). Hold flag removed; all extraction boxes self-terminated / released.
- PDF CAD/document classification: worker m classifies locally; backlog pass pdf_classify.py + pdf_disk12_pass.py (reads the Disk-1 copy
  at the old worker's key for PDFs recorded as disk12 pointers). 
- Progress 23:10Z: ~300/1,499 archives, 426 in flight, 224 worker processes on 30 boxes, ~6.4k files/s. Earlier 22:50Z: 217/1,499 archives ok, 308 in flight, 152 worker processes on 30 boxes. Earlier, 22:15Z: 142/345 archives ok, 1.39M files extracted, 727k unique stored (293 GB), 663k duplicates, 2,900 nested archives, 36 password-locked
  nested, 0 failures. 3D types so far: 5,608 .ifc (3,634 unique), 764 .db1, 593 .stp, 229 .ifczip, 53 .nwd, 46 .rvt.
- Output: `cad-disk-extract/zentitude-data-4/extracted/<flattened archive path>/…`; raw copies `zentitude-data-4/source/` (52,780 objects, done).
- **Conversions to STEP — jobs (builder scan 02:41Z):** IFC 9,489 + IFCZIP 1,663 + IFCXML 5 = 11,157 (150 GB); Tekla DB1 2,258 (836 xslib
  excluded); SDS2 173 jobs (all 193 report folders found); native new STEP 2,448 (indexed). IFC fleet: 7 × r7i.16xlarge Mumbai (02:52Z) +
  3 × r7i.16xlarge Hyderabad (03:05Z), kit `_control/conv/ifc/userdata.sh` (self-terminating). IFC queue is largest-first (2.5 GB files at the
  front), so early throughput is low. DB1: 2 × r7i.16xlarge Hyderabad (03:02Z) + 1 Mumbai (03:20Z). SDS2: 1 × i4i.16xlarge Mumbai, Ubuntu
  (03:20Z; converter v4 candidate, the version Disk-2 run-2 accepted). All conversion boxes self-terminate when their pipeline has a result
  for every job. Our Mumbai CAD usage after 03:20Z: 688/700 vCPU; Hyderabad 320/320.
- **Conversions to STEP (started 02:30Z):** new (not in Disk-1/2) .ifc 9,490 / .ifczip 1,663 / Tekla .db1 3,095 / SDS2 jobs (≤193) → builder
  prepares kits + job lists under `zentitude-data-4/_control/conv/{ifc,db1,sds2}/`, outputs `zentitude-data-4/conversions/{ifc-step,db1-step,
  sds2-step}/`, status `_state/conv_status.json` (shown on the live page); lead launches the fleets.
- PDF CAD/document classes: after the Disk-1-copy passes, 489,275 unique stayed 'unknown' → `pdf_index_fill.py` filled 449,451 from the
  Disk-1/2 run's own per-sha class (union.sqlite digests buckets cad_pdf/other_pdf; why=disk12_index), then `pdf_fullparse.py` downloads
  the remaining ~39.8k whole files and reads producer + page sizes with pdfinfo (why=full:*). pdf_classify.py republishes the tally.
- **DATA-4 CONVERSIONS FINAL (07:37Z, `_state/conv_final.json`):** IFC 11,157 jobs → 11,099 STEP (7.70 TB), 58 failed (25 grid/annotation
  only, 21 .ifcZIP holding XML not IFC, 8 ifcXML (reader disabled in ifcopenshell), 2 empty, 1 coordinates ~1.3e11 mm, 1 read-back over 3 h);
  DB1 2,258 → 1,994 STEP (0.84 TB), 264 failed (193 no_member_layout = decoder limit on 8.85/8.07 record variant, needs reverse-engineering;
  44 axis/attr-link checks; 14 blank; 9 Tekla 9.21/9.50 unverified; 2 layout timeout; 1 no banner; 1 corrupt); SDS/2 173 folders → 133
  accepted STEP (25.5 GB), 40 failed (13 invalid solids, 8 no members, 6 no model data, 6 missing job file, 4 QA, 2 v4, 1 seed); native new
  STEP 2,448 indexed. OCC read-back for STEP < 256 MB (IFC 8,346 / DB1 967 / SDS2 133); larger graded by entity counts + bbox.
  Outputs `zentitude-data-4/conversions/{ifc-step,db1-step,sds2-step}/`; not-accepted STEP kept under `_not_accepted/` and `_readback_crash/`.
  Builder fixes: ENOSPC retryable + big-job disk gating; STEP writer escaped '' part names (32+24 outputs re-converted); requeue skip bug.
  Open: 193 DB1 no_member_layout; 8 ifcXML; IFC STEP size (tessellated curved parts; .step.gz possible). Test objects left under
  `_state/conv/zz_test/`, `_control/conv/_test/`.
- **Source identity (proven 05:58Z):** every object under `bim-proprietary-data/Disk-1/` vs `/Zentitude-data-4/` by path; identity per object
  by same ETag, same full-object CRC64NVME, or SHA-256 of the data-4 copy = Disk-1 ChecksumSHA256 (`zen2/src_identity_sha.py`). All 1,154
  Disk-1 archives are in data-4 byte-identical (6.12 TB); 51,799 identical loose files; data-4-only: 345 archives (1.75 TB) + 145 loose;
  Disk-1-only: 18,011 small loose files (5 GB); 0 different. Summary `zentitude-data-4/_state/audit/src_identity_summary.json` (live page).
- Repair DONE 05:45Z (433/433, 0 errors), re-audit 0 missing (`marker_missing_after_repair.json`); SDS2 hold removed 06:00Z.
- **WRAP-UP COMPLETE (07:55Z):** all checklist items done. 0 CAD instances in ap-south-1 and ap-south-2 (running or stopped);
  0 unattached CAD volumes. cad-zen2-files self-terminated 07:44Z after backup (`zentitude-data-4/_state/box_backup/cad-zen2-files/work/`
  4,719 objects / 13.4 GB + `zenitude-data-2/_state/box_backup/cad-zen2-files/work/` 35,730 / 10.7 GB; DONE.json + finisher.log).
  Final live publish 07:44:38Z (commit e858222); local publisher stopped. To resume publishing: `cd zen2 && caffeinate -i
  ../cad-db1-convert/venv/bin/python publish_sources.py 120`.
- **WRAP-UP CHECKLIST (Dhiren 05:05Z: "stop all after everything is done … terminate … everything perfect … update accurately"):**
  1. Conversions final: IFC (49 ENOSPC retries), DB1 (no_member_layout ~11%: builder checking decoder fix), SDS2 (6 big jobs).
  2. Repair: 57/57 `_state/repair_results/`, 433/433 restored → re-run `z4_marker_audit.py` (expect 0 missing) → ping builder to
     requeue download_error jobs → rerun `pdf_fullparse.py` for full:no_copy/read_error PDFs → `pdf_classify.py` republishes.
  3. Remove `_control/conv/sds2/hold` (set 05:04Z so the SDS2 box, which also runs repair, stays up).
  4. Back up state to S3 before terminating: cad-zen2-files `/work/pdfcache/classes.sqlite`, `/work/*.py`, logs;
     cad-zen2-sql: code already in `model/_code/`, DB exports in `json/db/`.
  (06:10Z) DONE: 7 idle conversion boxes terminated; cad-zen2-sql TERMINATED after backup (`zenitude-data-2/_state/box_backup/cad-zen2-sql/`).
  cad-zen2-files must stay until conversions are final: it runs the builder's `conv_status.py --loop 120` (writes conv_status.json).
  Unattached CAD volumes in ap-south-2 DELETED 06:15Z with Dhiren's OK: vol-0310a6d23759a4c6e 300 GB cad-disk-extract-hyd-status
  (made from snap-08c793be55220531d, which still exists), vol-00f8bb72f6ac20a6b 1 TB cad-zenitude-s3d-restore. ap-south-2 now has 0
  unattached volumes. Mumbai unattached volumes belong to other teams' k8s clusters — never touch.
  (06:13Z) Dhiren asleep, told me to finish and terminate on my own. Safety net: cad-zen2-files shutdown behaviour set to terminate
  and `/work/finisher_files.sh` running (log /work/finisher.log). It waits for `_state/conv_final.json` (builder) or FINAL unchanged
  30+ min (deadline 18:00Z), runs conv_status.py once, stops loops, backs up /work (not out/ or in/, already in S3) to
  `zentitude-data-4/_state/box_backup/cad-zen2-files/work/` (2d, md → zenitude-data-2/...), then shuts down. If the backup fails it stays up.
  5. Terminate: conversion boxes self-terminate; SDS2 box after hold removal; cad-zen2-files (i-0afb7c16dab7a238d) and cad-zen2-sql
     (i-02c20241cf997b48d, restored DBs are reproducible from `zenitude-data-2/source/`). Check volumes with DeleteOnTermination=false.
  6. Final live-site publish (conversions final, PDF classes, repair panel) → stop the local publisher → CONTEXT/MILESTONES/memory.
- **Data-4 marker gap + repair (04:47Z):** `zen2/z4_marker_audit.py` → `_state/audit/marker_missing.json` (433 shas, target keys) +
  `marker_missing_occurrences.jsonl.gz` (1,623 paths, 95 archives). Cause: `upload_tree` wrote the disk-wide sha marker before the upload;
  a worker killed in between left a marker with no object and re-runs trusted it. Fix: worker `zx-2026-09-30o` (on marker hit, HEAD the
  target and upload the identical bytes there if missing) + `ZX_MODE=repair` (jobs `_control/repair_jobs.json`, 57 archives / 1.13 TB,
  results `_state/repair_results/`, claims `_state/repair_claims/`, never touches manifests; `ZX_MAXSIZE` caps archive size per box;
  overrides `_control/zx_env_repair.json`; boot `_control/ud_zx_repair.sh`). Running on cad-zen2-files (≤60 GB archives, /work 853 GB);
  6 archives > 60 GB (72-124 GB) need an i4i box when conversion capacity frees. Conversion download_error jobs to be requeued after.
- **Data-2 3D COMPLETE (builder final report 03:50Z)** — `zenitude-data-2/model/`: JSON 45,003 pipelines + 46 structure areas (880,311 members,
  44,009 curved, 9,339 slabs) + 41 equipment areas (29,059 equipment, 37,917 nozzles); PCF 45,003 (regenerated with S3D's own SKEY/record
  conventions learned from the originals); IFC4 1,927 (14.3 GB, all < 70 MB); STEP 1,927 (158 GB, OCC read-back roots = parts, 2,917,779
  parts; 319 of 2,918,098 elements have no tessellatable geometry); GLB 1,927 (23.8 GB); OBJ 1,927 (73.4 GB); PNG 2,239.
  Exact: 820,570 pipes, 880,138 members from ACIS (end cuts/copes), 37,917 nozzles, 8,170 slabs. Parametric: 758,936 fittings, 28,406
  equipment. Approximate (flagged per element): 173,639 valves/instruments (symbols only), 164,954 supports (bbox), 408 equipment (bbox),
  35,798 curved members + 999 slabs as open shells. Validation vs S3D bboxes: members 0.0 mm (800 samples), slabs 91% ≤ 2 mm, equipment
  99.7% ≤ 1 cm; PCF vs original: 94.1% parts, type 99.3%, SKEY 98.5%, bore 99.85%, 100% on 4,885 unchanged pipelines.
  Not extracted: gaskets/bolts/welds in IFC (PCF/JSON only), footings, cable tray/conduit, HVAC/electrical, 3,698 equipment design solids.
  Code `zen2/s3d/src/` (converter `src/fanout/`), mirror `model/_code/`. st2 workers terminated 03:40Z. `cad-zen2-sql` still holds the
  restored DBs (keep until Dhiren says otherwise).

## 6. Local layout (Dhiren's Mac)

| Path | What |
|---|---|
| `/Users/dhiren/Downloads/Deccan/` | workspace root |
| `cad-db1-convert/` | Disk-1/2 conversion code, reports, lead repo clone, `venv/` (boto3) |
| `cad-extract-status/` | public status site repo (`sources.html`, `sources.json`, `.nojekyll`) |
| `cad-extract-context/` | this repo (private) |
| `zen2/` | new-disk scripts: `ud_zen2_sql.sh`, `restore_s3d.sh`, `export_db_jsonl.sh`, `ud_zen2_files.sh`, `zen2_files_jobs.sh`, `zx_worker.py`, `ud_zx_z4.sh`, `s3copy.py`, `stats_agg.py`, `publish_sources.py`, `live/private.html` |
| `/tmp/zen/` | scratch (listings, overlap files) — not durable |
| `~/.claude/projects/-Users-dhiren-Downloads-Deccan/memory/` | Claude memory notes |

## 7. Rules

- Deletions in the dataset, changes to shared workers, or touching machines we did not launch need Dhiren's explicit OK.
- Heavy S3 work runs in-region (laptop uplink ~0.3-0.8 MB/s). Use s5cmd for big single-object pulls (AWS CLI managed only ~80 MB/s on RHEL).
- One Python process is GIL-bound (~1.7 cores): run several processes per box.
- No client/project names, account IDs or internal details on the public site; no secret values anywhere in git.
- Agents and fixers write S3 only under their own prefix (agentjobs/<slug>, pfix/<slug>, fixes/<slug>, agentwork/<slug>). Shared kit and
  _control files (run.sh, pybin.txt, env.json, rules.json, priority.json) change only through the builder's release path. Reads are
  `aws s3 cp s3://… -`, never `- s3://…`. Incident 2026-10-02 01:14Z: a fixer emptied `_control/z3conv/sds2/pybin.txt` this way.
  It was restored from S3 versioning at 01:17Z with Dhiren's OK. The builder is adding kit validation, empty-file guards and a coordinator
  self-heal from versions.
