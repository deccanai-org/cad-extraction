# Packaging (projpkg4)

## 1. Format

projpkg4 is the team lead's package format (reference: deccanai-org/cad-dataset-packager; Disk-1/2 notes in
`docs/history/PACKAGING_CONTEXT.md`). One **project** = one extracted archive folder; project id =
`<Disk>__<flattened archive path>`.

```
<project>/
  project.json            summary (counts, duplicates_collapsed, excluded_non_asset_files, unresolved, ...)
  manifest.jsonl          one row per file: path, channel, sha256, size, source key, step class / partial info
  model/{step,ifc,db1,db2,sds2,stl}/
  drawings/{pdf,dwg,dxf,dg,dpm}/
  fab/nc1/
  tables/{bom,abm,kiss,drawing_index}/
  scripts/                (added later by the parametric phases; never rewritten by the packager)
```
Flat paths (one directory per channel), 6-hex suffix on name collisions, sha256 for every file, store-mode zips for
SDS/2 jobs (`model/sds2/<job>.zip`).

## 2. Generations

| Generation | Root | Code | Result |
|---|---|---|---|
| Disk-1/2 (09-24 → 09-26) | `dataset/main/{3d,2d}/` | `src/cad-db1-convert/src/pkg_step.py`, `ops_2026-09-25/pkg_final.py` | 2,476 packages (1,286 3d / 1,190 2d incl. 5 empty), 34,270 STEP; 3d iff any STEP |
| Superseded first attempt | `packaged/` | — | wrong format, ~18M objects, delete awaiting owner |
| **General packager — perfect tier** (10-02 → 10-06) | `dataset/packages/3d/` | `src/z3conv/package/pkg.py`, `pkgcore.py`, `adapter_zen3.py`, `adapter_zen4.py`, `coord_hook.py` | **779 projects** |
| **Partial tier** (10-05 → 10-06) | `dataset/packages/3d_partial/` | same, `PKG_TIER=partial` | **2,418 projects** |

Original packager copy + audit/spec + proposed patches: `src/cad-packager/` (`AUDIT.md`, `SPEC.md`, `RUN.txt`).

## 3. Rules (owner)

- Only projects with ≥1 shipped model; shipped = class 1 (perfect tier) / class 2 (partial tier).
- **Deduped everywhere**: each model placed once, in its primary project (pkg-2026-10-02d): the stored data-3 copy wins;
  otherwise not backup / library / copy, then most files, then first id. Sticky primaries across rounds.
- A project already in `3d/` gets a partial **add-on** in `3d_partial/` with only its partial STEP and
  `converted_from_package → 3d/<pid>`.
- Delta rounds add newly shipped models; removals are queued (`removals_pending.jsonl`) until the owner approves.
- Files that were dedup pointers (`disk12:` / `prior:`) are resolved to a proven source key (UploadPartCopy SHA-256
  proof) — maps under `_state/packaging/pkg-resolver-d4/`; truly missing files are listed in `project.json`.

## 4. Runtime

- Coordinator hook (`coord_hook.py`) writes jobs (`_state/conv/package/jobs*.json`); package workers / coordinator
  scripts apply them: `src/z3conv/tools/z3c_backup/pkgperf_loop.sh` (z3pkgperf-loop), `pkgp_loop.sh` (z3pkgp-loop),
  `pkg_d4_apply*.sh`, `pkg_files_run.sh`.
- Verify: `pkg.py verify --adapter zen3|zen4` / `pkg_verify_par.sh` (read-only); checks such as `step_not_shipped`,
  `orphan_queued_for_removal`, sha mismatches.
- Finisher: `src/z3conv/tools/z3c_backup/finisher.sh` (systemd z3finish) — waits for conversion queues to drain, runs
  final deltas + verify, writes `FINISH_DONE.json` (copy in `docs/evidence/`).

## 5. Final state (`docs/evidence/FINISH_DONE.json`, `stats_f1.json`, `stats_p1.json`)

| | Perfect (3d) | Partial (3d_partial) |
|---|---|---|
| Projects | 779 | 2,418 (1,756 standalone + 662 add-ons) |
| STEP | 12,718 distinct class-1 | 26,733 (2,012 complete_to_source / 24,721 approximated) |
| Distinct files | 15,507,077 | 5,462,092 |
| Bytes | 5.20 TB | 26.85 TB |
| Verify | 761/779 ok; 18 only `step_not_shipped` (38 STEPs) | 2,418/2,418 ok |
| Removals pending owner | left-shipped 131 (+8 projects), dedup_non_primary 647 (+28 projects), sha_mismatch_orphan 113, dup_step 6, orphan 1 | sha_mismatch_orphan 4 |

Package-level audit of roots, add-on dedup and cross-root sha overlap: `docs/evidence/pkg_audit.json`.
