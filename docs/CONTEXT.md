# CONTEXT — the whole CAD data-extraction programme

Owner: Dhiren (Deccan AI; times were given to him in PDT). Work ran 2026-09-2x → 2026-10-08, mostly by Claude Code
sessions and sub-agents driving an AWS fleet. This file is the synthesized narrative; the raw, chronological logs are in
`docs/history/` (newest-first `CONTEXT_live_log.md`, `HANDOVER.md`, `BUGS.md`, `MILESTONES_source.md`,
`HANDOFF_CAD_STEP.md`, `PACKAGING_CONTEXT.md`, `PII_PLAN.md`, `memory/`). Numbers here are cited in `NUMBERS.md`.

---------------------------------------------------------------------------------------------------------------------

## 1. Goal (owner's words, condensed — HANDOVER.md §1)

1. Extract every source disk fully (every file, nested archives to the deepest level), deduplicated across disks.
2. Convert every IFC, Tekla DB1 and SDS/2 model on every disk to STEP, "perfectly, with all fixes and all versions".
   **Never fabricate geometry.**
3. Classify every STEP into exactly three classes: **1 perfect**, **2 partial** (what is missing and what is needed is
   listed), **3 bad**.
4. Verify independently (our grader plus a verifier modelled on a teammate's per-format verifiers).
5. Package every class-1 STEP with its archive's files in **projpkg4**, automatically; deduped: one model in ONE
   package across all disks, no repeated projects; only archives with ≥1 class-1 primary model.
   Later (10-05) a second, **partial tier** for class-2 models.
6. One full report per disk; counts at every stage.
7. Later phases: PII redaction (planned, not applied) and parametric build123d scripts (separate repo).

## 2. The source disks

All source disks were uploaded (by others) to `s3://bim-proprietary-data/` (ap-south-1). See `AWS_MAP.md`.

| Disk | Size | What | Relationship |
|---|---|---|---|
| `Disk-1/` | 1,154 archives, 6.12 TB | Tekla / IFC steel-detailing project backups | **Byte-identical subset of data-4** (proved per object, 2026-09-30) |
| `Disk-2/` | 2,466 archives, 3.25 TB | mostly SDS/2 jobs + Tekla | **Subset of data-3** (2,474 data-3 archives identical by path+size) |
| `Zenitude-data-2/` | 223 GiB | Hexagon Smart 3D v13 SQL Server backup of plant MLNG@1 + unrelated ADNOC P16093 piping drawings | Census + own decoder only; not customer steel models |
| `Zenitude-data-3/` | 774,328 objects, 3.86 TiB (4.24 TB compressed) | 2,980 archives + loose folders; mostly SDS/2 jobs | Superset of Disk-2 |
| `Zentitude-data-4/` (sic) | 53,443 objects, 7.90 TB, 1,499 archives | 8 TB "TeklaBackup" SSD | Superset of Disk-1 (+345 archives, 1.75 TB) |

Final per-disk origin split of the 779 perfect-tier projects (report v4, 10-06): data-3 213 (Disk-2 161 +
data-3-only 52), data-4 566 (Disk-1 356 + data-4-only 210).

## 3. Phase 1 — Disk-1 / Disk-2 (2026-09-2x → 09-26)

- Extraction fleet (17 i4i workers, ap-south-1 + ap-south-2) extracted 3,620/3,620 archives, **CAD extensions only**
  (.pdf .dxf .dwg .dg .dpm .stp .step .ifc .db1 .sat .obj .stl .gltf .glb .nc1 + archives).
- 2026-09-23 13-hour stall: root cause = **password-protected nested zips** made 7-Zip prompt for a password, got EOF,
  and aborted the parent (rc 255). Fix: always pass `-p` (empty password); record encrypted members.
- Tekla DB1 → STEP: our own decoder (`src/cad-db1-convert/src/db1dec.py` → IFC via `db1step.py` → STEP via
  `ifc2step5.py`), 13 × r7i.16xlarge + a Windows RE box running the original `db1tostep.exe` pipeline.
  8,837 of 9,609 in-scope DB1 converted; 772 not convertible without guessing.
- IFC → STEP: 8,764 of 9,129 distinct IFC (365 cannot: 353 grid-only, truncated, all-zero, OLE2, CIS/2).
- Packaged into projpkg4 at `dataset/main/{3d,2d}/`: **2,476 packages, 34,270 STEP** (6,220 native / 14,652 IFC /
  13,398 DB1). These were *not graded* into classes; Disk-1/2 content was later re-done inside data-4 / data-3.
- Code: `src/cad-db1-convert/`. Handoff: `docs/history/HANDOFF_CAD_STEP.md`, `PACKAGING_CONTEXT.md`.

## 4. Phase 2 — the Zenitude disks

### 4.1 Zenitude-data-2 (Smart 3D) — 2026-09-29/30
- Restored the five SQL Server backups (model DB 164 GB, 814 tables / 15,267 views) on a SQL Server 2022 box; exported
  1,875 tables to JSONL (10.9 GB gz).
- Found geometry in plain columns (pipe ports, path features, welds, member axes, nozzles, bboxes) → own decoder
  (`src/zen2/s3d/`) → 45,003 pipelines JSON + PCF, 1,927 IFC4 → 1,927 STEP (2,917,779 parts) + GLB + OBJ + PNG.
  Rebuilt PCF vs Smart 3D originals: 94.14% of 779,546 parts matched within 1 mm.
- 549,831 drawing documents stored inside the model DB exported (170,569 isometric .sha, 50,675 original PCF, …).
- Census only for classification: its IFCs are derived from Smart 3D, not customer models (owner).
- **Contains credentials in SharedContent (`SSP3D1.ini`, `*.cci`) — never copied anywhere, never publish.**

### 4.2 Zentitude-data-4 — extraction 2026-09-29 → 09-30 00:32Z
- Worker `src/zen2/zx_worker.py` (versions a → o): full 7-Zip 24.08 extraction, empty password, nested archives into
  `<name>!/` to depth 15, ransomware-encrypted files flagged, **disk-wide sha256 dedup** (first writer stores, others get
  a pointer `sha256:<hash>`; files < 64 KB stored per archive), dedup against Disk-1/2 (`disk12:sha256:` pointers via a
  16.36M-prefix index), claims by S3 conditional writes, hot reload, versioned stop flag.
- Fleet: 30 × i4i.8xlarge (20 Mumbai, 10 Hyderabad), ~6.4k files/s.
- FINAL: 1,499/1,499 archives, 117,573,886 files (18.49 TB), 18,656,435 unique objects stored (4.88 TB), completeness
  1,490/1,490 vs the drive report, 0 upload errors. A marker-before-upload bug left 433 contents missing; worker `o` +
  repair mode restored 433/433, re-audit 0 missing.

### 4.3 Move annotationprod → bim-proprietary-data — 2026-09-30
All work moved from `s3://annotationprod/cad-disk-extract/` to `s3://bim-proprietary-data/cad-disk-extract/` (same
keys): 37,110/37,110 shards verified by size + ETag (`src/zen2/move/move_worker.py`). The annotationprod copy was then
purged with a verified delete (153.6M keys) — except `_control/`, which stays there because the Mac logins cannot write
the bim bucket.

### 4.4 Zenitude-data-3 — extraction 2026-09-30 → 10-01 03:36Z
- Same worker (`p`/`q`/`r`), jobs from the drive report: 2,980 archives + loose-folder jobs (5,992 jobs total); dedup
  index Disk-1/2 ∪ data-4 = 27,675,351 distinct (`prior:sha256:` pointers).
- FINAL: 5,992/5,992 jobs (5,924 ok, 57 partial, 11 failed — all source damage), 372,225,432 files (15.23 TB raw),
  41.7M unique (5.04 TB), 35.7M new vs earlier disks (3.47 TB); object audit 168,010,409 objects, 0 missing, 0 orphans.

## 5. Phase 3 — STEP conversion, grading, verification, classification (10-01 → 10-06)

See `STEP_CONVERSION.md` and `CLASSIFICATION.md` for detail.

- Pipelines: **IFC** (`ifc2step6`, final 6.1.10; 6.1.11-rc2 canaried, not promoted), **Tekla DB1** (own decoder, final
  code u/v), **SDS/2** (`sds2-step-pipeline` v5.5.x, final v5.5.11), each run on a shared fleet runtime
  (`src/z3conv/common/convfleet.py`) with best-of across converter versions per model.
- Exact duplicates converted once (by sha). Data-3 first; data-4 (+Disk-1) via "disk lanes" (`CONV_DISK`), reusing
  data-3 results by sha.
- **CONVERT → VERIFY (two independent checks) → CLASSIFY** (deterministic merge in `coord/build_index.py`).
- Tolerance policy: one deterministic 0.1 mm (converter sew / gap); never keyed on OCC read-time healing.
- Final classes (10-06): data-3 2,509 / 5,743 / 367; data-4 11,309 / 21,568 / 1,217 (+19 no input).
- Fleet peak ~28 boxes / 1,728 vCPU (Mumbai, Hyderabad, Singapore); coordinator `i-039e769ea62de0fa1`.

## 6. Phase 4 — packaging (10-02 → 10-06)

See `PACKAGING.md`.
- General packager (`src/z3conv/package/pkg.py` + `pkgcore.py`, adapters per disk) in projpkg4.
- **Perfect tier** `dataset/packages/3d/<Disk>__<archive path>/`: class-1 models only, one primary package per model
  across all disks: **779 projects, 12,718 class-1 STEP, 5.20 TB**.
- **Partial tier** `dataset/packages/3d_partial/` (`PKG_TIER=partial`): class-2 models with `partial.kind`
  (complete_to_source | approximated) + issues/missing/standins; a project already in 3d gets an add-on holding only
  its partial STEP: **2,418 projects, 26,733 STEP, 26.85 TB**.
- Package files resolved across disks (`disk12:` pointers → proven sha→key map, 197,090 sha for data-4).
- Finisher `src/z3conv/tools/z3c_backup/finisher.sh` drained everything and wrote `FINISH_DONE.json` (10-06 14:44Z).

## 7. Phase 5 — reports

- Per-disk data-pack report (perfect tier): `src/report_v1/build_report.py` → private artifact
  https://claude.ai/artifact/3YT7fcZYVGm1AAAiY1AFrR (v4, 10-06).
- Separate partial-tier report: `src/report_v1/build_partial_report.py` → https://claude.ai/artifact/LcKzPRdac52VD2TTUsUQwF.
- Public anonymous status site: https://dhigdec.github.io/cad-extract-status/ (`sources.html`, `graded.html`,
  `partial.html`, `parametric.html`), published from AWS / the Mac (`src/cad-extract-status/`, `src/zen2/publish_sources.py`).
- Disk-1/2 era report: `src/cad-db1-convert/report_final/`.

## 8. Phase 6 — parametric (build123d) scripts

- 5 Disk-1 sample projects (33 models, 42,199 parts) → `dataset/samples/parametric_v1/<project_id>/` (projpkg4 copy +
  inputs/ + scripts/ + verification/). v7: 42,176/42,199 parts, 28/33 models perfect.
- Full corpus run **pmx** (10-07 →): every perfect-tier class-1 model (12,735 jobs) on a ~2.7–3.1k vCPU fleet; state
  `_state/pm_full/`; scripts publish into each package's `scripts/`. Status 10-08 07:37Z: 11,832 processed, 7,835
  perfect. **Code and docs: https://github.com/deccanai-org/parametric-cad** (not duplicated here).
- Partial tier → completed models (**pmp**, on Modal): `src/partial_modal/`; 5-sample tests, colour-coded issue models,
  publishes into `3d_partial/<pid>/scripts/`. Scaling waits for the owner's cost approval.

## 9. Key decisions (owner unless noted)

- Never fabricate geometry; standard-derived / estimated parts are tagged `[approx: …]` and never count toward class 1.
- One primary per SDS/2 job (all saved states converted; best class → most parts → coverage → latest saved).
- Open source meshes: no gap filling; tagged surfaces, class 2.
- Dedup: deduped everywhere; one model → one package; existing duplicate copies kept unless deletion approved.
- Data-3 first, then data-4; data-2 census only.
- Tekla env bolt catalog allowed as info tag; SDS/2 holes derived from bolt records count as exact; guessed bolts stay class 2.
- 6.1.10 final ("Option A"); 6.1.11 not promoted.
- Volume rule (10-05): a part within 0.5% of its source kernel volume is exact even if the file's stated quantity differs.

## 10. Open items (as of 2026-10-08)

- Removals awaiting owner OK (perfect tier: 131 left-shipped + 8 projects, 647 dedup_non_primary + 28 projects, 113
  sha_mismatch_orphan, 6 dup_step; partial: 4) — `FINISH_DONE.json`. 18 perfect projects fail verify only on
  `step_not_shipped` until those are applied.
- 1 DB1 model (`2a7c0357…`, data-4) never finished (starved on a small box).
- 54 data-4 source files NoSuchKey in 18 projects (absent from the extraction); 89 Disk-1/2 files truly missing.
- Fixes written but owner-deploy-blocked: pkgcore `read_manifest` split, SDS2 build_index run_code fix.
- annotationprod: 381,102 noncurrent-only versions kept (ask before deleting); old `cad-disk-extract/packaged/` copy.
- PII redaction: plan only (`docs/history/PII_PLAN.md`).
- Parametric: pmx toward the owner's 11,000-perfect goal; pmp scaling decision.
