# Milestones (UTC)

| When | Milestone |
|---|---|
| 2026-09-23 | Root cause of 13 h extraction stall found: password-protected nested zips made 7-Zip prompt; fixed with `-p` + skip/record |
| 2026-09-24 | Disk-1/Disk-2 extraction 3,620/3,620; first projpkg4 packaging verified |
| 2026-09-25 | Tekla DB1→STEP fleet (13 × r7i.16xlarge + RE box) and IFC→STEP runs; end-game packaging automation |
| 2026-09-26 05:26 | Disk-1/2 finished: 2,476 packages, 34,270 STEP (6,220 native / 14,652 IFC / 13,398 DB1), all checks 0; all our EC2 terminated |
| 2026-09-28/29 | Others ran SDS/2→STEP (r1, r2 paused 06:53Z 09-29), meshwork, and a zenitude-data-2-restore copy (not ours; audit pending) |
| 2026-09-29 20:45 | Session resumed in Claude Code CLI; SSO re-login; access verified (bim, annotationprod-publish OK; audit role removed; new CAD-Disk-Extract-Operator role) |
| 2026-09-29 21:00 | Three new source disks found in `bim-proprietary-data`: Zenitude-data-2 (223 GiB), Zenitude-data-3 (3.86 TiB), Zentitude-data-4 (7.90 TB) |
| 2026-09-29 21:05 | Zenitude-data-2 identified: Smart 3D v13 backup (model 167 GB, catalog, site, SharedContent) + P16093 piping drawings |
| 2026-09-29 21:12 | Restore box `cad-zen2-sql` i-02c20241cf997b48d launched (SQL Server 2022 Standard LI, egress-only) — pulling the backup set |
| 2026-09-29 21:16 | Site + catalog backups restored (SQL Server 2019 backups → 2022) |
| 2026-09-29 21:36 | Zentitude-data-4 extraction canary launched; 38/38 first archives ok, 50% file-level dedup |
| 2026-09-29 21:41 | 8 more i4i.8xlarge launched for Zentitude-data-4 (345 new archives, 1.745 TB) |
| 2026-09-29 21:47 | **Zenitude-data-2 model DB MLNG@1_MDB restored** (164 GB, 814 tables, 15,267 views) |
| 2026-09-29 21:50 | Live page for the new disks published: https://dhigdec.github.io/cad-extract-status/sources.html |
| 2026-09-29 21:52 | Found plain coordinate columns in the S3D model (pipe ports, path features, welds, members, nozzles, bboxes) → own 3D decoder planned |
| 2026-09-29 22:09 | Zenitude-data-2 DB→JSONL export done (1,875 tables, 10.9 GB gz); drawings: 131 DXF, 2,146 PNG pages; SharedContent unpacked (34,186 files) |
| 2026-09-29 22:10 | Audit of 2026-09-26→29 activity complete (Codex SDS/2 runs, orphaned ap-south-2 volumes, frozen Disk-1/2 feed) |
| 2026-09-29 22:25 | Dhiren's goal: extract ALL of Zentitude-data-4 (incl. 1,154 Disk-1-equal archives, since Disk-1 kept only CAD types), deepest level, nothing skipped |
| 2026-09-29 22:28 | Phase B job list (1,154 archives, IFC/STEP first) + 11 more Mumbai + 10 Hyderabad i4i.8xlarge → 30 boxes / 960 vCPU |
| 2026-09-29 22:40 | Worker fixes: non-UTF-8 member names (cp1252 + raw hex kept), hot reload + versioned stop flag (zx-2026-09-29e) |
| 2026-09-29 22:50 | Data-2 3D build started (builder agent): parsed JSON + PCF for 45,003 pipelines, then IFC → STEP/glTF/OBJ/PNG; S3D mapping shows ~56% exact / ~34% parametric geometry without a licence |
| 2026-09-29 23:05 | Worker g (direct PUT) doubles data-4 upload rate to ~6.4k files/s; completeness check vs drive report: 267/267 listed archives match |
| 2026-09-29 23:12 | Worker h: per-job liveness for claim takeover (no archive can be blocked by a crashed process) |
| 2026-09-29 23:20 | Dedup vs Disk-1/2 (worker k): content already stored by Disk-1/2 is never uploaded again; existing 407 GB of copies kept per Dhiren |
| 2026-09-29 23:36 | Worker l: takeover of ~350 archives orphaned by the retired old workers (in flight 5 → 155+); 1,149/1,499 archives done |
| 2026-09-30 00:15 | Worker n: long file names (>255 bytes) recovered via 7z stdout fallback; 2 archives re-run |
| 2026-09-30 00:32 | **Zentitude-data-4 COMPLETE + VERIFIED**: 1,499/1,499 archives, 117.6M files, completeness 1,490/1,490, source copy 52,780/52,780, 0 upload errors |
| 2026-09-30 00:36 | Data-2 3D fan-out: 15 × c7i.16xlarge (10 Mumbai, 5 Hyderabad) converting 1,520 IFC → STEP/GLB/OBJ (1,598 jobs) |
| 2026-09-30 01:00 | Data-2 3D conversion done: 1,927 IFC → 1,927 STEP (all validated), GLB, OBJ; conversion fleet released 01:17 |
| 2026-09-30 01:05 | Found 549,831 drawing documents inside the model DB (170,569 isometric .sha, 50,675 original PCF, Isogen XML/POD) → exporting; real 2D↔3D pairs |
| 2026-09-30 01:10 | Live page: Disk-1 / Disk-2 vs Z4 'what is new' comparison per file type (unique sha256) |
| 2026-09-30 02:00 | Model-stored drawings exported: 549,831 documents (170,569 isometric .sha, 50,675 original PCF, 126,905 Isogen XML, 46,873 POD, …), full-oid keys |
| 2026-09-30 02:00 | Data-4 PDFs whose content is only in Disk-1 classified from the Disk-1 copies (830,755); parallel backlog pass for the rest running |
| 2026-09-30 02:52 | Data-4 IFC→STEP fleet launched (7 × r7i.16xlarge; +3 Hyderabad 03:05) for 11,157 new IFC/IFCZIP jobs |
| 2026-09-30 03:00 | Data-2 2D complete: 1,083 PDF pages → validated DXF, 170,518 model .sha decoded, 50,675 isometrics from original PCFs |
| 2026-09-30 03:20 | SDS2 kit ready → 1 × i4i.16xlarge launched (173 jobs); +1 DB1 box (Mumbai); 2 workers for data-2 structure v2 (138 st2__ chunks from 880k ACIS solids); Mumbai 688/700, Hyderabad 320/320 |
| 2026-09-30 03:35 | Data-4 PDF unknowns 489k → 40k: 449,451 classified from the Disk-1/2 run's own per-sha PDF class; full-file pdfinfo pass for the rest |
| 2026-09-30 03:40 | Data-2 structure v2 done: 138 st2 chunks (880,138 ACIS member solids with end cuts, 43,959 curved members, 9,169 slabs) → STEP/GLB/OBJ, all OCC-validated; st2 workers terminated, +1 IFC box |
| 2026-09-30 03:50 | **Data-2 3D COMPLETE**: 45,003 JSON+PCF, 1,927 IFC → 1,927 STEP (2,917,779 parts, OCC roots = parts) + GLB + OBJ + 2,239 PNG, pairing index; publisher per-suffix count bug fixed (PNG counts were copies of DXF counts) |
| 2026-09-30 04:00 | Data-4 PDFs: only 245 unique / 489 raw left unclassified (full-file pdfinfo pass); CAD 6.75M raw / 2.95M unique (new 836,532), non-CAD 1.93M / 954,129 (new 60,342) |
| 2026-09-30 04:47 | **Data-4 gap audit:** worker wrote sha marker before upload → killed workers left 433 distinct contents (1.73 GB, 1,623 occurrences, 95 archives) with a marker but no object (of 471,478 pointer-only shas checked). Worker 'o' heals on marker hit; repair mode re-extracts 57 archives (1.13 TB) and uploads to the marker targets |
| 2026-09-30 05:45 | **Repair complete:** 433/433 missing contents restored (57 archives, 0 errors); re-audit 471,478 checked, **0 missing** |
| 2026-09-30 05:58 | **Disk-1 ⊂ data-4 proven byte-for-byte:** all 1,154 Disk-1 archives (6.12 TB) are on data-4 identical (225 ETag, 735 CRC64NVME, 194 SHA-256) + 51,799 identical loose files; data-4 adds 345 archives (1.75 TB) + 145 loose; 0 differ (`_state/audit/src_identity_summary.json`) |
| 2026-09-30 06:00 | PDFs final: data-4 unknown 21 unique (16 not PDF, 3 encrypted, 1 read error, 1 zero-byte); data-2 drawing set 298/299 → CAD |
| 2026-09-30 06:10 | Cleanup (Dhiren): terminated 7 idle conversion boxes (6 IFC, 1 DB1; 0 running jobs, checked twice) and cad-zen2-sql (builder outputs/logs/code backed up to `zenitude-data-2/_state/box_backup/cad-zen2-sql/`, 105,296 objects / 17.9 GB; restored DBs reproducible from `zenitude-data-2/source/`) |
| 2026-09-30 06:15 | Deleted the 2 unattached CAD volumes in Hyderabad (300 GB + 1 TB) with Dhiren's OK; ap-south-2 has 0 unattached volumes |
| 2026-09-30 07:37 | **Data-4 conversions FINAL:** IFC 11,099/11,157 → STEP (7.70 TB); DB1 1,994/2,258 (0.84 TB); SDS/2 133/173 (25.5 GB); 2,448 native STEP; every failure has a recorded genuine reason; all conversion boxes self-terminated or were terminated when idle |
| 2026-09-30 07:55 | **Wrap-up complete:** cad-zen2-files backed up and self-terminated; 0 CAD instances or unattached volumes left in either region; final live-site publish 07:44Z; publisher stopped |
| 2026-09-30 | PII for CAD PDFs: reviewed reference AudioPII-QC (document arm, CAD marked not-ready); sampled real CAD PDFs; plan in `PII_PLAN.md` (awaiting owner decisions) |
| 2026-09-30 | PII plan v3 (strict policy, in place, OpenRouter ZDR) saved; on hold until the annotationprod → bim-proprietary-data transfer is done |
| 2026-09-30 20:55 | Move annotationprod/cad-disk-extract → bim-proprietary-data/cad-disk-extract started (after the admin narrowed the role's Deny); 14 mover boxes; ETag-exact verification |
| 2026-09-30 21:26 | Zenitude-data-3 extraction started into bim-proprietary-data (12 i4i boxes, jobs from the drive report: 2,980 archives + 746 loose folders; dedup vs Disk-1/2 + data-4, 27.7M known) |
| 2026-09-30 23:55 | **Move annotationprod → bim-proprietary-data COMPLETE:** 37,110/37,110 shards verified (size + ETag per object; 37,070 direct, 40 via split sub-shards); ~135M+ objects / 60+ TB; throttle failures fixed by redo rounds r1–r3 and tail split (x). Live site now reads Z4/Z2 from the bim bucket. **Deletion from annotationprod deferred until data-3 finishes (Dhiren).** |
| 2026-09-30 23:55 | Data-3: move capacity reused → 20 × i4i.8xlarge Mumbai + 5 × i4i.16xlarge Hyderabad; 121 throttle-partial jobs re-queued; S3 coverage fix added 6 archives + 563,866 loose files (5,992 jobs); SDS2 job counting added to stats and site |
| 2026-10-01 03:36 | **Zenitude-data-3 COMPLETE + VERIFIED:** 5,992/5,992 jobs, 0 upload errors; 2,980/2,980 report archives match (+6 not in report); 766,619/766,619 loose files; 372.2M files (15.23 TB raw from 4.24 TB compressed), 41.7M unique (5.04 TB), 35.7M new vs Disk-1/2/Z4 (3.47 TB); object audit 168.0M objects, 0 missing / 0 orphans; PDFs CAD 1,302,277 unique (222,598 new), documents 672,698, 29 not PDFs; SDS2 7,267 job folders / 2,157 unique. annotationprod purge pending owner go |
| 2026-10-01 → 10-02 | Data-3 STEP conversions in max-effort mode: ifc2step6 6.x, DB1 codes j→r, SDS2 v5→v5.5; CONVERT → VERIFY → CLASSIFY design; tolerance 0.1 mm |
| 2026-10-02 08:10 | annotationprod verified purge done: 153,604,435 keys deleted where bim holds an identical copy |
| 2026-10-02 21:51 | Data-3 FINAL r1 written (graded); independent verification in progress |
| 2026-10-02 22:05 | Packaging stage started: general projpkg4 packager, perfect tier `dataset/packages/3d/`, deduped primaries |
| 2026-10-03 05:15 | Phase 2 (other disks): data-4 disk lanes on; Disk-1 ⊂ data-4, Disk-2 ⊂ data-3; data-2 census only |
| 2026-10-04 | Data-4 packaged: 519/519 jobs, 9,141 class-1 models; full read-only verify of 731 packages; 6.1.10 final (Option A) |
| 2026-10-05 | Report v2 published; owner asks for a partial tier (`PKG_TIER=partial`, `dataset/packages/3d_partial/`) |
| 2026-10-06 14:44 | **FINISH_DONE**: perfect 779 projects (761 verify-clean), partial 2,418 (all clean); classes final; report v4 + separate partial report |
| 2026-10-06 | Parametric samples: 5 Disk-1 projects, 33 models → build123d scripts (`dataset/samples/parametric_v1/`), v7 28/33 perfect |
| 2026-10-07 | Full-corpus parametric run (pmx) on ~2.7k vCPU; repo deccanai-org/parametric-cad; partial-tier pmp on Modal (5-sample tests) |
| 2026-10-08 | pmx 11,832/12,735 processed, 7,835 perfect; this repo (cad-extraction) assembled |
