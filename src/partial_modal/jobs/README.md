# jobs/ - partial-tier job list + pre-signed GET URLs (pmp)

Everything here is **read-only against S3** (`AWS_PROFILE=bim`, IAM user `dhiren@deccan.ai`, HEAD/GET/LIST only).
Nothing here runs geometry, the pipeline or a decoder. Nothing here writes to S3.

| file | what |
|---|---|
| `make_jobs.py` | builds the job list: one row per partial model (all 26,733 in 2,418 packages) |
| `presign.py` | job row(s) -> pre-signed GET URLs (SigV4, 7 days) for every input a Modal job reads; `--check` / `--test` |
| `s3cache.py` | read-only S3 helpers (head, head_sha256, ls, get) + local cache under `cache/` |
| `jobs_partial.jsonl.gz` | **the job list** (deterministic gzip, sorted by pid, model_folder) |
| `jobs_stats.json` | tier statistics + every problem class with counts and examples |
| `jobs_problems.jsonl` | one line per (model, problem): nothing is dropped silently |
| `new5.jsonl` | the 5 NEW test models (from `../new5.json`, each row = the full job row + `tag`) |
| `urls/` | URL files (0600, git-ignored): `new5.urls.json`, `new5.signed.jsonl` (job rows + `urls`) |

There is deliberately **no `test5.jsonl`**: the original 5 samples must never run on Modal.

## Run

```bash
cd /Users/dhiren/Downloads/Deccan/partial_modal
AWS_PROFILE=bim .venv/bin/python jobs/make_jobs.py            # whole tier (~5-15 min; cached afterwards: ~2-3 min)
AWS_PROFILE=bim .venv/bin/python jobs/make_jobs.py --new5-only # only the 5 test packages (seconds)
AWS_PROFILE=bim .venv/bin/python jobs/presign.py --jobs jobs/new5.jsonl --check --test \
    --out jobs/urls/new5.urls.json --embed-out jobs/urls/new5.signed.jsonl
```

`make_jobs.py` HEADs every package `manifest.jsonl` on every run (ETag + size); a package whose manifest changed is
re-read (rows + `model/` listing). Conversion-detail lookups are cached per model (`cache/detail/`), keyed by the
conversion output key + its ETag; `--refresh` re-reads them. `presign.py --check` re-verifies every signed object
against the job row at signing time, so a stale row can never be signed silently (exit 2).

## Job row schema (`jobs_v = pmp-jobs-2026-10-07a`)

| field | meaning |
|---|---|
| `model_id` | conversion model id (IFC/DB1: sha256 of the source file; SDS/2: 24-hex job id). Unique over the tier -> job id, Modal volume folder `/<model_id>/`, bundle name `<model_id>.tar.gz` |
| `pid`, `relpath` | package id; delivered STEP path in the package (`model/step/...`) |
| `model_folder` | `scripts/<model_folder>/`: STEP basename with every run of chars other than `A-Za-z0-9._-` -> `_`, max 80; on a case-insensitive clash among ALL partial models of the package, or a reserved name (`README.md`, `requirements.txt`, `steelbuild.py`, `issues_lib.py`, `scripts_manifest.jsonl`, `__pycache__`, `con`, `nul`, `com1`...), every member gets `-<model_id[:8]>` (`[:16]` if still clashing). Same rule as the perfect tier's `stage_full.py` |
| `step_source` | `ifc` / `db1` / `sds2` |
| `partial_kind` | `approximated` / `complete_to_source` |
| `bytes`, `class` | delivered STEP bytes; `S` < 10 MB, `M` < 100 MB, `L` < 500 MB, `XL` < 1 GB (decimal), `too_big_v1` >= 1 GB (out of scope for v1, kept in the list) |
| `source_class` | same rule on the source file (IFC / DB1 / SDS/2 zip) bytes - information for resource choice |
| `step` | `{key, bytes, sha256, etag, listed}` - the package copy of the delivered STEP |
| `source` | `{kind, format (ifc / ifczip / ifcxml / ifc_no_ext / db1 / sds2_zip), relpath, package (3d_partial / 3d), pkg_prefix, key, bytes, etag, sha256, sha256_from (package_manifest / s3_full_object_checksum), exists, sha256_is_model_id}` |
| `addon` | true = the partial package is an add-on of the perfect `3d/<same pid>/` package and the source lives there (`converted_from_package`) |
| `conv` | conversion output the package copied: `{step_key, step_bytes, step_etag, same_as_delivered, folder, files[{key,bytes,etag,mtime,role}]}` (files next to the output, written by the same run) |
| `state` | `{dir, results{key,...,summary,matches_shipped}, files[{...,role,matches_shipped}]}` from `<disk>/_state/conv[2]/<kind>/{results,detail}/<id>.*` |
| `detail_keys` | `{alias: key}` - ONLY files proven to belong to the shipped conversion run. IFC: `parts_json`, `check_json`, `stats_json`, `results_json`, `src_parts`, `step_parts`, `census`, `attrib`, `result_detail`, `render_png`; DB1: `parts_json`, `check_json`, `results_json`, `src_parts`, `step_parts`, `census`, `decoded_parts`, `render_png`; SDS/2: `pieces_csv`, `skipped_csv`, `log`, `manifest_json`, `job_json`, `render_png` (+ `results_json`, `state_*` only when the state result JSON names the shipped STEP) |
| `pin` | IFC: `{code, writer_suffix (v6110...), results_code}`; DB1: `{code, kit (kit_v / kit_u / kit_q), kit_evidence, engine, catalog_overlay, decoded_skipped}`; SDS/2: `{version, version_folder, run (v5_fleet / r2_v4 / v4_fleet), label, zip, zip_sha256, code, evidence}` |
| `partial`, `grader`, `verify_verdict`, `verify_codes`, `older_revision_of`, `sds2_primary`, `also_model_ids` | copied from the package manifest row |
| `manifest` | `{key, etag, bytes, placed_at}` of the package manifest the row came from (freshness proof) |
| `problems`, `severity` | stable codes (below); severity = worst of `info` < `degraded` < `blocking` < `excluded`, `ok` when none |

"Proven to belong to the shipped run": IFC/DB1 - the result JSON's `out_key` is the row's `step_key` and its
`out_bytes` the delivered bytes, and a state file's writer/kit suffix (`.v6111.`, `.u.`) is the shipped STEP's (an IFC
model can hold v6110 and v6111 detail side by side); SDS/2 - the result JSON names the shipped `step_key`. Files next to
the conversion output (same folder, same stem) are written by the run that wrote the STEP; `conv.same_as_delivered`
proves that output is still the delivered bytes (size + ETag).

### Problem codes

| code | severity | meaning |
|---|---|---|
| `too_big_v1` | excluded | delivered STEP >= 1 GB |
| `step_not_in_package` / `step_size_mismatch` | blocking | delivered STEP missing / size differs from the manifest |
| `source_missing` / `source_size_mismatch` | blocking | source file not listed / size differs |
| `pin_lost_kit` | blocking | DB1 produced by a lost kit (q) |
| `source_sha256_not_model_id` | degraded | IFC/DB1 source sha256 is not the model id |
| `source_ifcxml` | degraded | source is ifcXML |
| `conv_step_missing` / `conv_step_differs` | degraded | conversion output gone / no longer the delivered bytes |
| `results_missing` | degraded | no result JSON |
| `conv_detail_missing` | degraded | no parts/check (IFC/DB1) or pieces/skipped (SDS/2) next to the conversion output |
| `pin_unresolved` | degraded | the producing converter version could not be pinned to a kit/zip |
| `results_not_shipped_run` | info | the state result JSON is another run (e.g. a later re-run of an r2/v4 SDS/2 model): use `conv/` files only |

## URL set per job (`presign.py`)

`step`, `source`, `detail/<alias>` for every `detail_keys` alias (render PNG only with `--png`; `--detail all` adds
every side file incl. other runs', flagged `matches_shipped=false`). `new5.signed.jsonl` = the job rows + `urls`
(`{name: url}`) + `urls_expire_at`: pass a row as-is to the Modal function. URLs are bearer tokens: files are 0600,
never printed, never committed. Long-term IAM-user keys are required (session credentials would expire the URLs early;
refused unless `--allow-session-creds`).
