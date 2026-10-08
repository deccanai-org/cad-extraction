# Packaging context: CAD archives → projpkg4 dataset (with converted STEP)

For handing to another agent. State as of 2026-09-26 (final). AWS account 874846752452, bucket `annotationprod`,
region ap-south-1. Read-only access: profile `bim`. Writes/deletes/SSM: SSO profile `annotationprod-publish`.

## 1. What the deliverable is

`s3://annotationprod/cad-disk-extract/dataset/main/` in the team lead's **projpkg4** format:

```
dataset/main/
  3d/<project>/      projects that hold at least one STEP model (native or converted)
  2d/<project>/      everything else (drawings, NC files, tables, unconvertible models)
```

- One **project** = one physical extracted archive folder (3,620 archives → 2,484 folders; 622 Disk-2 archives
  stored no new files because of content dedup). Project id = `<Disk>__<flattened archive path>`, e.g.
  `Disk-1__TEKLA-HYD_PROJECT_DATA-2021-2022_Steel_Fab_20._31318_-_Trex_HQ.7z`.
- Final counts: **2,476 packages = 1,286 in 3d + 1,185 in 2d + 5 empty** (archives with only non-asset files:
  `project.json` only). 34,270 STEP files: 6,220 native, 14,652 from IFC, 13,398 from Tekla DB1.

## 2. Layout inside a project

```
project.json
manifest.jsonl
model/step/  model/ifc/  model/db1/  model/db2/
drawings/pdf/ drawings/dwg/ drawings/dxf/ drawings/dg/ drawings/dpm/
fab/nc1/
tables/bom/ tables/abm/ tables/kiss/ tables/drawing_index/
```

- **Flat**: one directory deep per channel, no archive sub-folders. Name collision → 6-hex suffix
  (`name-a1b2c3.ext`), derived from the source S3 key so it is reproducible.
- **Content dedup inside a project**: a (channel, ETag, size) content is stored once
  (`project.json.duplicates_collapsed` counts the dropped copies). Projects are self-contained, so the same file
  can legitimately exist in two different projects.
- Non-asset files (archives, temp files, etc.) are excluded and counted (`excluded_non_asset_files`).

### manifest.jsonl (one row per file)

Lead's fields (every row): `project_id, relpath, modality, role, bytes, sha256 (null), parser_ok, units,
supersedes, etag, source_key` (`source_key` = where the file came from in `cad-disk-extract/Disk-X/...`).

Extra fields we add on **STEP rows**:
- `step_source`: `native` (from the archive), `ifc` (converted from an IFC in the project), `db1` (converted from
  a Tekla DB1, by us or the original Windows pipeline)
- `converted_from`: relpath of the source file in the same project (e.g. `model/db1/X.db1`)
- `converter`: e.g. `db1dec+db1step (db1-2026-09-25g) -> ifc2step5.py --mode hybrid --prec 2`
- optional: `also_converted_from` (other sources that produced the byte-identical STEP that was collapsed),
  `refreshed_at` (copy replaced with a repaired conversion)

### project.json

Lead's fields (`id, source, units, domain, status, route, slots{model_step,model_ifc,model_db1,...},
model_formats, drawing_formats, missing, warnings, files, bytes, duplicates_collapsed, packaged_at, ...`) plus:
`conversions{ifc:{step_added,converter,added_at}, db1:{...}}`, `model_step_by_source{native,ifc,db1}`,
and where applicable `removed_empty_step`, `step_duplicates_collapsed`.
Invariants: `files` = manifest rows, `bytes` = sum of row bytes, `slots.model_step` = STEP rows, `route` matches
the folder.

## 3. How the converted STEP got in (order of passes)

1. **Base packaging** (`pkg_final.py`, lead's format): extraction output → projects, routed 3d/2d.
2. **IFC pass** (`pkg_step.py`, `PKG_SOURCES=ifc`, then `ifc2` for late finishers): each packaged
   `model/ifc/*` → conversion id `<packaged ETag>_<size>` → `conversions/ifc-step/<id>.stp` → copied to
   `model/step/<stem>.step`.
3. **DB1 pass** (`PKG_SOURCES=db1`): each `model/db1/*` row → manifest `source_key` → sha256 via census /
   job list → `conversions/db1-step/<sha256>.stp` (only results with status ok on the final decoder code).
4. **2d → 3d move**: a 2d project that gains a STEP is copied object-for-object to `3d/`, verified, then the 2d
   copy is deleted. Never in both routes.
5. **Retag**: every STEP row gets `step_source`; `project.json` gets `model_step_by_source`.
6. **End-of-run corrections** (operator passes, scripts in `cad-db1-convert/src/ops_2026-09-25/`):
   - 123 DB1 copies had a STEP that was never placed: their source object had a different S3 ETag (multipart vs
     single-part upload) than an identical twin. Fixed by also matching on the **packaged** object's ETag+size
     (`pkg_posthoc_run.py`): 179 STEP placed in 138 projects, 82 moved 2d→3d.
   - 168 header-only STEP files (no geometry) from the original Windows pipeline's failed runs removed from 43
     projects (`empty_step.py`; no project lost its last STEP).
   - 31 byte-identical STEP files collapsed in 25 projects (`dedup_step.py`; kept row lists `also_converted_from`).
   - Repaired conversions re-copied into packages (`refresh_packaged.py`: 11 IFC + 2 regenerated DB1 + 2 Teton re-runs).
   - Empty test package `Disk-1___probe` removed.
   All deletions were approved by Dhiren.
7. **Full verify** (`verify_dataset.py`, 16 shards, run in-region): checks no STEP in 2d, every 3d has STEP, no
   project in both routes, every row has its object and vice versa, sizes match, slots match, every STEP row has a
   source, `converted_from` exists, no duplicate content, no conversion placed twice. **Final result: every check
   0 on all 2,476 packages.**

## 4. Control files in S3 (`cad-disk-extract/_control/packaging/`)

| Prefix | Content |
|---|---|
| `step_v1_ifc/`, `step_v1_ifc2/`, `step_v1_db1/`, `step_v1_db1_posthoc/`, `step_v1_db1_posthoc2/` | `plan.json` (every placement: project, name, out_key, converted_from, move_to_3d) + `done/<project>.json` |
| `endgame/` | markers and box scripts of the automated end-game |
| `verify/` | latest full verify (`<i>_of_16.json`); `verify_endgame/` = the earlier one |
| `dedup_step/`, `empty_step/` | plans + per-project done records |
| `refresh/report.json` | last refresh run |

## 5. Code (on this Mac)

`/Users/dhiren/Downloads/Deccan/cad-db1-convert/src/`: `pkg_step.py` (plan / apply / retag; `PKG_SHARD=i/N`,
`PKG_SOURCES`), `pkg_step_posthoc.py`, `refresh_packaged.py`, `verify_dataset.py`;
`src/ops_2026-09-25/`: `pkg_final.py` (base packager), `pkg_posthoc_run.py`, `dedup_step.py`, `empty_step.py`,
`ph_*.sh` (how they were run on an EC2 box via SSM). Lead's format notes: `cad-db1-convert/lead-repo/`.

## 6. Rules for anyone touching it

- Run heavy passes **in-region** (EC2 + SSM), not from the laptop (uplink ~0.5 MB/s, manifests are large).
- Always plan first, apply second; passes are idempotent per project (`done/` records).
- Move = copy all → verify → delete 2d copy. Never delete before the copy verifies.
- Don't delete from the dataset or bulk-delete anything without Dhiren's OK.
- Re-run `verify_dataset.py` after any change and expect every check at 0.
- Open item: old wrong-format copy at `s3://annotationprod/cad-disk-extract/packaged/` (~18M objects) is not part
  of the deliverable; deletion awaits Dhiren's decision.
