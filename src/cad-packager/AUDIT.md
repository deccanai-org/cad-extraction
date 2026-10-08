# AUDIT: PACKAGING_CONTEXT.md (Disk-1/2 projpkg4 packaging) checked against reality

Audited 2026-10-02 (read-only). Sources: the code in `cad-db1-convert/src/` and `src/ops_2026-09-25/`, the lead's repo
(`lead-repo/` = GitHub `deccanai-org/cad-dataset-packager` HEAD d3e4ed9), the control files in annotationprod
`_control/packaging/`, and the real packages in `s3://bim-proprietary-data/cad-disk-extract/dataset/main/{3d,2d}/`
(10 sampled projects + listings).

## Verdict

**Mechanics and numbers: correct.** Every count that could be checked matches:
- 2,476 packages = 1,286 in 3d + 1,190 in 2d (1,185 + 5 empty);
- 34,270 STEP = 6,220 native + 14,652 from IFC + 13,398 from DB1;
- 26,071,766 files, 20.68 TB;
- every end-of-run pass count (posthoc 179/138/82, empty_step 168/43, dedup_step 31/25, refresh 11+2+2);
- the final 16-shard verify (2026-09-26 01:57Z): every check 0.

**Location and access: outdated.** Also some errors and omissions that matter for any reuse; see the lists below.

## Wrong

- **"One project = one physical extracted archive folder."** Not quite. `project = f"{disk}__{tag}"[:200]` truncated ids, and that
  merged two groups of Disk-1 folders: 7 `…3456-BOP_STEEL_SEQ_*.zip` folders, and `…3456_CTG_10072016.zip` + `_LATEST.zip`. Only one
  folder per id was packaged, so **7 extraction folders (~24k objects) have no package**. 1,301 real Disk-1 folders → 1,294 ids. 136 ids
  are cut at exactly 200 characters.
- **"622 Disk-2 archives stored no new files because of content dedup."** They contain no wanted file types (mostly SDS/2 jobs). This
  matches the 2026-09-29 audit in CONTEXT.md §3.

## Outdated

- **Location.** The deliverable is now `s3://bim-proprietary-data/cad-disk-extract/dataset/main/`, moved 2026-09-30.
  `annotationprod …/dataset/main/` holds 0 current keys.
- **Access.** "Writes/deletes/SSM via annotationprod-publish" no longer applies to the dataset: the operator SSO profiles have an
  explicit deny on bim writes, and only the fleet role `cad-disk-extract-ec2` can write bim.
- **Hard-coded bucket.** All packaging scripts hard-code `B="annotationprod"`.
- **Old copy.** `annotationprod …/packaged/` was purged. The old wrong-format copy now lives at
  `bim-proprietary-data/cad-disk-extract/packaged/`; deleting it still needs Dhiren's OK.

## Incomplete or undocumented

- **Channels.** `model/sat` (1 project, 1,506 files) and `model/stl` (7 projects) exist but have no slot. `model/db2` and
  `tables/kiss` are empty everywhere: `.kss` was never mapped, and Disk-1/2 did not extract tables.
- **Pipeline artefacts shipped as data.** The worklist builder (`_control/packaging/pkgB0_worklist.py`, only in S3) pulled the old
  Windows DB1 pipeline's `derived/db1-step/…/by-sha256/<sha>/` folders into projects. Its report CSVs (`_failures.csv`,
  `_inventory.csv`, `_manifest.csv`, `part_schedule*.csv`) still sit in `tables/bom`: 381 of 1,043 table rows in 40 small projects.
- **Old-pipeline DB1 STEP rows (~2.8k)** have `step_source: db1` but no `converted_from` and no `converter`.
- **`etag` has two meanings.** On base rows it is the SOURCE object's ETag (58/1,900 differ from the packaged copy). On STEP rows it is
  the packaged copy's ETag. Content dedup used (ETag, size), so identical bytes stored as multipart under a different part layout were
  not collapsed.
- **Verify gaps.** `verify_dataset.py` never checks files = rows, bytes = sum or sha256. `sha256` is null on every row; `parser_ok` and
  `units` are asserted, not measured.
- **`model_formats.step`** is overwritten with the total STEP count, while native rows keep modality `stp` (sum 34,184 vs 34,270 rows).
- **Native STEP files (6,220) were shipped ungraded.**
- **Not listed in the doc.** Base packaging also ran on Windows boxes (`run_final_win.ps1`). Control prefixes `state/`, `state_v2/`,
  `report/`, `verify_test/`, `worklist_v2.json` and the `pkgA*`/`pkgB*` scripts exist but are not listed. `refresh/report.json` keeps
  only the last run; the earlier runs are in logs.
- **Unverifiable.** "All deletions approved by Dhiren": the only trace is a comment in `ph_stage_e.sh`.

## Correct

The doc is correct on:
- **Routing.** 3d = has a STEP, 2d = the rest. Verify: step_in_2d, 3d_without_step and both_routes are all 0.
- **Layout.** Flat channel directories; the 6-hex collision suffix is `sha256(source S3 key)[:6]` (279/279 checked).
- **Dedup and counters.** Content dedup inside a project; `excluded_non_asset_files` (191,353 in total).
- **Manifest fields and order.** `project_id, relpath, modality, role, bytes, sha256, parser_ok, units, supersedes, etag, source_key`,
  plus `step_source`, `converted_from` and `converter` on STEP rows.
- **Passes.** IFC pass (id `<packaged ETag>_<size>`), DB1 pass (sha via census / job list; codes g/f with status ok only), 2d→3d
  move (copy, verify, then delete), retag.
- **Control files** listed in §4: all exist, and the done counts equal each plan's project count.
- **Scripts.** All exist and do what is described.

## Differences from the lead's projpkg4 (`package_cad.py`) that our format does not share

- The lead's `scrub_to()` rewrote IFC, STEP, DXF and NC1 bytes to strip client strings. Ours (and the new packager) copy byte-exact, so
  **de-identification is still open**.
- The lead's `unique_name` hashed the local path, so it is not reproducible. Ours hashes the source key.
- The lead has 17 slots and ships SDS/2 natives per file (`model/mem|assm|group_mem`, `drawings/dtl|sht`, one job per archive). It
  parses KISS and BOM into `tables/<x>/data.jsonl`.
- `docs/PACKAGING_FORMAT.md` is a draft that the live tree does not follow.

## What the new general packager does because of this audit

- **No id truncation.** An over-long id becomes a 193-character prefix + `-` + 6 hex of the full id, and ids are asserted unique per
  plan.
- **Per row:** the packaged object's ETag and a real SHA-256 (S3-computed on copy); dedup by (channel, sha256).
- **Verify** checks files/bytes/slots, sha256 and orphans.
- **No pipeline outputs in tables.** Only extraction-manifest files plus graded, shipped STEP are packaged. Every converted STEP row
  carries `converted_from` and `converter`.
- **`.kss` → `tables/kiss`;** `xslib.db1` is tagged `component_library`.
- **Native STEP files are listed, not shipped, until graded.**
- **Ledger:** an append-only placement ledger replaces overwritten reports.
