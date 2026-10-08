# SPEC: general CAD packager (projpkg4, class-1 STEP only, automatic)

Version `pkg-2026-10-02b`. The code is in `code/`: `pkgcore.py` (core), `adapter_zen3.py` (data-3), `pkg.py` (CLI, delta, job),
`coord_hook.py`, `kit/worker.py` (`package` vpipe).

The core is disk-agnostic. Each disk plugs in through an adapter. Data-3 is the first adapter.

## 1. What gets packaged

**Unit.** One project = one physical extracted archive folder (or one loose-folder job) of a disk.
- Id: `<Disk>__<tag>`. `tag` = the disk's extraction folder name; for data-3 that is the archive path below `Zenitude-data-3/` with
  `/` → `_`.
- Ids are never truncated. If an id is longer than 200 characters, it becomes `id[:193]-<sha256(id)[:6]>`. The plan asserts that ids
  are unique.

**Which projects.** Only projects holding ≥ 1 **shipped** STEP. The route is always `3d`; there is no 2d route.

**Root.** `s3://bim-proprietary-data/cad-disk-extract/dataset/packages/3d/<project>/`, shared by every disk. The disk appears in the
id, in `project.json.source` and in `project.json.disk`. The old ungraded Disk-1/2 tree `dataset/main/` is left untouched.

**Shipped STEP.** Decided by `pkgcore.ship_decision`, one function:
- `class == 1` AND `grader_class == 1` AND `status == converted` AND a `step_key` is present.
- For pipelines whose verifier merges into the class (db1, sds2): also `verified == true` (build_index `verify_merge`) and
  verdict PASS or WARN.
- Rows whose failing or warning codes are only **held** (`verify_held`, codes S4/G5/G1/D4 pending adapter_sds2_v3) do **not** ship by
  default (`ship_verify_held=false`).
- IFC uses the grader class only (the verifier is an audit sample).

**Placement.** Each shipped STEP goes into **every** project whose archive holds a copy of its source (all `paths`). It sits beside
its source, which the project already contains.

**Not shipped.** STEPs of the project that are not shipped are listed in `project.json.steps_not_shipped`: model_id, pipeline,
class, reason, top 3 reasons, step_key.

## 2. Layout (projpkg4 as published in `dataset/main`)

```
project.json  manifest.jsonl
model/step model/ifc model/db1 model/db2 model/sds2 model/sat model/obj model/stl model/gltf model/glb
drawings/pdf drawings/dwg drawings/dxf drawings/dg drawings/dpm   fab/nc1
tables/bom tables/abm tables/kiss tables/drawing_index
```

**Channels.** Assigned by extension, as in `pkg_final.py`. Drawing role (shop/ga) and table channel (abm, kiss, drawing_index) come
from path keywords. Additions:
- `.ifczip` and `.ifcxml` → `model/ifc` (sources of shipped STEP);
- `.kss` → `tables/kiss`;
- `model/sds2` for SDS/2 jobs (see §4).
- `model/sat|obj|stl|gltf|glb` keep their directories but have no slot, as before.

**Naming.**
- Flat: one directory level per channel.
- Collision → `<stem>-<sha256(source)[:6]>.<ext>`. For files, `source` = `<archive key> :: <member path>`. For STEP, `source` =
  `step_key`.
- Names are assigned in sorted member order, so they are reproducible.
- A converted STEP is named `<source stem>.step`; an SDS/2 STEP is named `<job>.step`.

**Dedup.** Content dedup inside a project on (channel, sha256); `duplicates_collapsed` counts the dropped copies. The same file can
legitimately appear in two projects.

**Excluded.** Non-asset files are counted in `excluded_non_asset_files`. Zero-byte files are kept and counted.

**Natives.** STEP files found in the archive are **not graded**, so they are **not shipped**. They are listed in
`project.json.native_steps_not_graded`. (Recommendation and evidence: §6.) Policy `native_step_mode=ship` would place them in
`model/step` with `step_source: native, graded: false`.

**Byte-exact, additive.** Every packaged file is a server-side copy of the exact bytes. Nothing is rewritten and nothing is
de-identified; that stays an open item. The packager never deletes anything.

## 3. Fields

**manifest.jsonl** (one row per file).

Base keys, in this order: `project_id, relpath, modality, role, bytes, sha256, parser_ok, units, supersedes, etag, source_key`.
- `sha256` = real SHA-256. S3 computes it on copy (`ChecksumAlgorithm=SHA256`) and it is compared with the extraction manifest's
  digest. Zips are hashed at build time.
- `etag` = the packaged object's ETag.
- `source_key` = the physical object the bytes were copied from.

File rows add:
- `source_path` = `<archive key> :: <member path>` (the logical source);
- `source_bucket`;
- `resolved_by` (§5);
- `component_library: true` for `xslib.db1`.

STEP rows add:
- `step_source` (ifc | db1 | sds2 | native);
- `converted_from` (relpath of the source in the same project);
- `model_id`, `step_key`, `etag_source`;
- `converter {code, version}`;
- `class: 1`;
- `grader {grader_class, graded_by, corpus, domain, coverage_all, parts_source, parts_step, solids, invalid_solids, schema, reused,
  rerun_pending}`;
- `verify_verdict`, `verify_evidence`, `verify_codes`, `verify_held`;
- `sds2_primary`, `older_revision_of`;
- `source_paths_in_project`, `placed_at`, `refreshed_at`.

Every row also carries the reserved PII fields (§10): `pii_redacted: false` and `pii {method, verified, original_sha256, redacted_at}`
(all null until redaction).

**project.json.** The old keys stay: `id, source (<Disk>/<tag>), units, domain, year, status (complete|partial), route, slots,
model_formats, drawing_formats, missing, warnings, skipped_files, model_step_schemas, files, bytes, excluded_non_asset_files,
duplicates_collapsed, packaged_at, packaged_by`.
- `slots` has 11 keys: the old 10 plus `model_sds2`.

New keys:
- `disk, source_archive, source_kind, packager, sha256, zero_byte_files`;
- `conversions {pipe: {step_added, converter[], added_at}}`, `model_step_by_source`;
- `steps_not_shipped(_count)`, `native_steps_not_graded(_count)`, `unresolved_files(_count)`;
- `index_ref`, `policy`;
- `pii: {status: "not_redacted", files_redacted: 0}`.

**Invariants:** `files` = rows, `bytes` = Σ row bytes, `slots.model_step` = model/step rows, `route` = 3d, `id` = folder name.

## 4. SDS/2 sources: `model/sds2/<job>.zip`

An SDS/2 job is a folder; the converter reads `main/`, `mem/` and `subm/`. A projpkg4 `converted_from` must be ONE relpath. The
lead's per-file `model/mem|assm|...` layout loses the job structure and cannot be referenced, so this fits projpkg4 best.
- The zip holds **every file under the job folder**, stored without compression (exact bytes). Member names are `<job>/<path below
  the job folder>`, in sorted order, with a fixed timestamp, so the build is deterministic.
- Each member's SHA-256 is checked against the extraction manifest while streaming.
- The manifest row carries `job, source_path, fpc, jsetup_sha256, members_count, members_bytes, members_digest` (SHA-256 over sorted
  `path\tbytes\tsha256` lines) and `members_missing(_count)`. The full member list goes inline (`members`) up to 1,000 members.
  Above that, the zip's own central directory plus `members_digest` stand in. This is the closest consistent alternative to "member
  list in the row": a 136k-member list in one row would make manifest.jsonl unusable.
- **Completeness is required** (`sds2_zip_require_complete=true`). If any file of the job folder cannot be resolved, the SDS/2 STEP is
  not placed in that project; it is listed as not shipped with the reason.
- Individual assets inside the job folder (`.pdf`, `.nc1`, `.kss`, …) are also placed in their own channels.

## 5. Adapter interface (one per disk)

```
class Adapter:
  disk: str                                    # 'Zenitude-data-3'
  project_ref(archive_part) -> {project_id, tag, source_key, kind archive|dir, job_id, size, source_prefix}
  project_of(archive_part) -> project_id
  files(project) -> [{path, size, sha256, key, dedup}]      # the disk's extraction manifest for that archive / folder
  conv_rows(index_bytes=None) -> [common index rows]          # the disk's conversion index in the common schema
  resolve(project, items, sds2_fpc=None)                      # sets src_bucket / src_key / src_how per item (None = unresolved)
```

**Common index schema** (one row per converted model):
- identity: `model_key (<disk>:<pipe>:<id>), disk, pipeline, id, source_sha256, fpc, jsetup_sha256`;
- sources: `source_paths [(archive key, member path)]`, `step_bucket, step_key`;
- grading: `class, grader_class, reasons, issues, status, converter_code, converter`;
- verification: `verify_verdict, verify_evidence, verify_codes, verified, verify_held`;
- SDS/2 revisions: `sds2_primary, older_revision_of, revision_rank`;
- grader evidence: `corpus, domain, graded_by, coverage_all, parts_source, parts_step, solids, invalid_solids, schema, step_bytes,
  reused, rerun_pending`.

**Data-3 resolution order.** The plan records the order used per file in `resolved_by`:
1. the own data-3 object (`data3`, `data3_archive`);
2. the loose source object (`data3_source`);
3. the data-3 marker (`data3_marker`);
4. for `prior:` keys:
   - the sha-proven conversion-scan maps (`ifc_scan:*`, `sds2_scan`);
   - the data-4 marker (`data4_marker`);
   - data-4 manifests of sibling archives (`data4_manifest`);
   - the fleet-built data-4 small-file index (`data4_index`, built by `pkg.py build-d4-index`);
   - the Disk-2 / Disk-1 extraction of the byte-identical archive at the same path (`disk12_same_archive`).

The apply step proves every file: the S3-computed SHA-256 must equal the manifest digest, or the row is not written.

**Disk-1/2 adapter (to do).** Its extraction listings exist (prefixes `cad-disk-extract/Disk-N/<folder>/`; ids must reuse those folder
names, including the 12-hex suffix). It has no per-file sha256, so the packager computes it on copy. Its conversions (Disk-1/2 IFC and
DB1 STEP) must first be graded into the common index; today they are ungraded.

**data-4 adapter (to do).** Manifests carry sha256 (`zentitude-data-4/_state/manifests/<id>.jsonl.gz`, same row format as data-3).
`disk12:` pointers resolve like data-3's `prior:`. Its conversions must also be graded into the common index first.

**data-2.** A plant model, not archives. It would need a project definition first (for example one per area or pipeline).

## 6. Native STEP: recommendation

List them, do not ship them, until they are graded.

Evidence:
- They are not graded, while the deliverable promises class-1 STEP.
- The lead found `.stp` files holding CIS/2 structural data, not geometry (`cis2.stp`, `aisc2000.stp`). 23 lead archives had no
  CAD-openable STEP.
- The old dataset shipped 6,220 ungraded natives and so lost the "every model/step is graded" invariant.

Grading them with the same OCC read-back (step_check) would make them shippable as `step_source: native`.

## 7. Automation (ledger, delta, jobs, status)

State lives in `s3://bim-proprietary-data/cad-disk-extract/_state/packaging/` (fleet-writable).

**Per-project files:** `locks/`, `plans/<project>/<job>.json.gz`, `done/`, `ledger_parts/`, `verify_fail/`.

**Ledger.** `ledger.jsonl` has one row per (model, project): `model_key, project_id, step_key, step_etag, step_sha256, relpath,
converted_from, placed_at, refreshed_at`. `ledger_index.json` gives `model_key → {step_key, step_etag, step_sha256, projects[],
first_placed, last}`.
- Workers write only their project's `ledger_parts/<project>.json`, and only after verify passes.
- The coordinator compacts the parts each round; it is the single writer.

**Each coordinator round** (`coord_hook.round()` → `pkg.pkg_delta`):
1. shipped set minus ledger → one `package` job per affected project (create or update);
2. a shipped STEP whose `step_key` or ETag changed → refresh, which replaces the file at the same relpath and sets `refreshed_at`;
3. a model or placement that left the shipped set → `removals_pending.jsonl` (append-only, never applied);
4. writes the immutable index snapshot used by the jobs (`index_snapshots/<sha16>.jsonl.gz`), the jobs list (default
   `zenitude-data-3/_state/conv/package/jobs.json`) and `status.json`.

The status block goes into `conv_status.packaging`: `shipped_models, projects_with_shipped_step, projects_packaged,
steps_placed_models, placements, pending_jobs, pending_create, pending_steps, removals_pending, verify_failures, stuck_projects`.

**Job.** `kit/worker.py`, or `pkg.py job`.
1. Takes the project lock (S3 conditional create, refreshed every 5 minutes, stale after 2 h). If the lock is held → a transient
   retry.
2. Plans from the snapshot. An update keeps every existing relpath.
3. Copies server-side with an S3 SHA-256, builds SDS/2 zips on local disk, then rewrites `manifest.jsonl` and `project.json`.
4. Verifies, then writes the ledger part and the done record.

It is idempotent: an existing destination with an equal S3 SHA-256 is skipped. An open job keeps its id, so a project never gets a
second job. After 3 failed verifies a project is marked stuck for an operator.

## 8. Removal policy

Nothing is ever deleted by the packager. A model that leaves the shipped set (class change, new verifier verdict, superseded) is
appended to `_state/packaging/removals_pending.jsonl`: model_key, project_id, reason, queued_at.

Until the owner approves, the STEP stays in place. Verify reports it as `pending_removal`, which is information, not a failure.

Proposed approval channel: the operator writes `s3://annotationprod/cad-disk-extract/_control/packaging_d3/removals_approved.jsonl`
(the boxes can read it). A later `remove` job deletes only the listed STEP files, rewrites manifest and project.json, and re-verifies.
Not implemented yet: it needs the owner's go.

## 9. Verify checks (all must be 0; per project after each job, and dataset-wide with `pkg.py verify --all [--full-hash]`)

- **Objects vs rows:**
  - `missing_object`: a row without an object;
  - `orphan_object`: an object without a row;
  - `dup_relpath`.
- **Content:**
  - `size_mismatch`;
  - `etag_mismatch`: against the packaged object;
  - `sha_mismatch`: the S3-stored SHA-256, or a streamed hash for composite (multipart) objects with `--full-hash`;
  - `sha_unverified`;
  - `dup_content`: (channel, sha256).
- **STEP rows:**
  - `converted_from_missing`: the source relpath is not a row in the same project;
  - `step_not_shipped`: model_id not in the shipped set and not pending removal;
  - `step_key_changed`: the shipped STEP changed and the refresh is pending;
  - `no_shipped_step`.
- **project.json:** `pj_files`, `pj_bytes`, `pj_slots_step`, `pj_route_id`, `pj_pii` (files_redacted = rows with pii_redacted).
- **Rollback fields:** `pii_fields_missing`, `source_key_missing` (every non-zip row must name its source object).

## 10. PII redaction (later step, owner decision 2026-10-02)

Packaging runs now. Redaction comes later as a separate step that replaces drawing files inside the packages with redacted versions.

**Prepared now (implemented in pkg-2026-10-02b):**
- Every manifest row has `pii_redacted: false` and a reserved `pii` object `{method, verified, original_sha256, redacted_at}`.
- project.json has `pii: {status: "not_redacted", files_redacted: 0}`; verify checks it against the rows.
- Every row records `source_key`, the untouched source object, which is the rollback copy (bim versioning is OFF).
  - SDS/2 zips record `members_list_key` (member source keys and sha256, in `_state/packaging/sds2_members/`) so they can be rebuilt.
- The packager never modifies or deletes sources.

**Replace hook `pkg_replace(project, relpath, new_bytes_key, meta)`: designed, NOT implemented.** The permission classifier blocked
adding in-place overwrite code for dataset objects in this session, so it needs the owner's explicit go.

Design, under the same per-project lock (`locks/<project>.json`):
1. Server-side copy of the redacted bytes over the packaged object, with an S3 SHA-256.
2. Update the row: `bytes`, `sha256`, `etag`, `pii_redacted: true`, `pii {method, verified, original_sha256 (= the previous sha256,
   kept on repeat runs), redacted_at}`. `source_key` stays unchanged.
3. Rewrite manifest.jsonl, then project.json (`files`, `bytes`, `pii`).
4. Re-run `verify_project`.

It is idempotent: a row already redacted with the same new sha256 is a no-op. STEP and zip rows are refused.
