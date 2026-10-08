---
name: project-zenitude-report
description: "Teammate-style data-pack report for the Zenitude disks (data-3 + data-4) — artifact URL, generator, data pipeline, gotchas"
metadata:
  node_type: memory
  type: project
  originSessionId: cc2df5a5-2f05-4112-ac6d-adb750ab0b8a
  modified: 2026-10-05T21:20:32.833Z
---

Report artifact (private): https://claude.ai/artifact/3YT7fcZYVGm1AAAiY1AFrR. It mirrors the section structure of the teammate's page
du1aeao3w2p10.cloudfront.net (CAD-STEEL-FLEET-001). It adds an "Every disk" section (conversion classes plus packaged per disk, with Disk-1 and Disk-2 subsets)
and a "How perfect is established" section. v2 was published 2026-10-05 from stats run t4 (774 projects, 15,493,010 distinct files, 5.14 TB).

- Generator: `~/Downloads/Deccan/report_v1/build_report.py [RUN]`, plus report.css and report.js. Output goes to report_v1/site/. Republish the same file_path to keep the URL.
- Stats: `/tmp/z3c/rep_stats_t4.sh` runs on the coordinator, takes ~2.5 min, and computes Disk-1/Disk-2 pseudo-disk distinct counts. Then rep_push.sh and an s3 cp of
  `_state/report/out/stats_<RUN>.json` + projects_<RUN>.json into report_v1/data/. SSM does NOT pass env vars, so copy the script with a new RUN default.
- Class numbers: data/class_now.json, built from the d3/d4 index.jsonl.gz (Disk-1 = z4_disk12_duplicates archives; Disk-2 = data-3 rows reused from disk-1/2 or disk-2).
- Artifacts cannot serve .glb, so models ship as models/<tag>.json ({glb: base64}). The GLBs are already Y-up, metres and centred (no -90° rotation).
- Local preview: the server must run from the scratchpad (Downloads cwd raises PermissionError), via the launch.json entry zen-report-site.

Related: [[project-cad-extract-pipeline]], [[project-zenitude-disks]]

## Partial tier (owner 10-05/06)
- Packager switch PKG_TIER=partial (package/pkgcore.py, pkg.py, adapter_zen3.py; perfect behaviour unchanged when unset).
  Root `dataset/packages/3d_partial/`, state `_state/packaging_partial`, jobs `_state/conv/package_partial/`. Class-2 STEP rows carry partial.kind (complete_to_source | approximated) + issues/missing/standins.
  A project already in 3d/ gets an ADD-ON: only its partial STEP, with converted_from_package → 3d/<pid> (owner: "deduped everywhere").
- DB1 partials ship only on code v (PKG_PARTIAL_REQUIRE_CODE).
- Coordinator services: `/tmp/z3c/pkgp_loop.sh` (z3pkgp-loop, kit /opt/pkgpartial/kit, canary then all) and `/tmp/z3c/pkgperf_loop.sh` (z3pkgperf-loop, perfect tier, /opt/pkgd4r2/kit). Stop with `/opt/pkg{partial,perf}/stop`.
- Data-3 dry run: 1,429 projects (152 add-ons + 1,277 partial-only), 5,743 STEP.
- Report v3 has exact origins (Disk-2 = 2,474 data-3 archives identical by path+size, /opt/report/disk2_in_z3.json): 352 Disk-1 / 209 data-4-only / 161 Disk-2 / 52 data-3-only.

## FINAL (2026-10-06 ~8:00 AM PDT) — report v4 published
- Perfect tier: 779 projects (data-3 213, data-4 566: Disk-1 356, data-4-only 210; Disk-2 161, data-3-only 52), 12,718 distinct class-1 STEP,
  15,507,077 distinct files, 5.20 TB. Verify: 761/779 clean, and 18 fail only step_not_shipped (38 STEPs of demoted models awaiting the owner's removal OK).
- Partial tier (packages/3d_partial/): 2,418 projects (1,756 partial-only + 662 add-ons), 26,733 partial STEP (2,012 complete_to_source /
  24,721 approximated), 26.85 TB, 5,462,092 distinct files. Verify 2,418/2,418.
- Classes final: data-3 2,509/5,743/367; data-4 11,309/21,568/1,217 (+19 no input). One DB1 model (2a7c0357, Littleton, 30.7 MB) was starved on
  i4i.2xlarge and not waited for.
- Removals pending the owner's OK: perfect left-shipped 131 + project 8, dedup_non_primary 647 + project 28, sha_mismatch_orphan 113, dup_step 6; partial 4.
- Finisher: /tmp/z3c/finisher.sh (z3finish), incremental verify cache /opt/finish/verify_*_cache.json; helper scripts are backed up in z3conv/tools/z3c_backup/.
- Lessons: SDS2 zips with 40–60k tiny members are GIL-bound in one process → fan zips out to the fleet (zip_prebuild.sh; zip reuse by members-digest metadata).
  Do not add tiny boxes (i4i.2xlarge) for DB1: a 30 MB model starved there. macOS deletes old /tmp files: keep scripts in z3conv/tools/.

## Separate PARTIAL report (10-06, owner asked "same structure as the perfect one")
- Artifact https://claude.ai/artifact/LcKzPRdac52VD2TTUsUQwF (file report_v1/psite/index.html; perfect report stays 3YT7fcZYVGm1AAAiY1AFrR).
- Build: `python3 report_v1/build_partial_report.py p1` -> psite/ (65 MB > 64 MB per publish: publish twice, 2nd adds models/t5.p0/p1.json). Shared report.js now loads split models (`{"parts":[...]}`; host limit 16 MB/file).
- Samples in report_v1/s3mirror/passets/{pmodels,ppdf,prange,pjoin,pthree}; cloud scripts (backed up in z3conv/tools/z3c_backup): rep_joinscreen_p2.sh, rep_joinassets_p2.sh, rep_range_p.sh (range + 220-dpi three-ways crops), rep_title_p.sh.
- Lessons: NC1 headers can carry a `** file.nc1` comment line after ST, which shifts every field (old parser found 0/613 joins; fixed → 44 full agreements). partial_issues.json must count each shortfall ONCE PER MODEL over the packaged model_ids (old per-entry count gave 38,831 concrete prisms > 4,379 SDS/2 models). 35 models (38 files, 3 code-u DB1 models in 2 perfect packages each) are class 1 in 3d/ and class 2 in 3d_partial/ — on the removal list awaiting owner OK.
