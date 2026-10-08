# publish/ - getting per-model results from Modal into the packages' `scripts/` folders

Modal has no AWS credentials. Each model's results travel as ONE bundle (`<model_id>.tar.gz`) that Modal uploads with
a pre-signed PUT URL to a staging key. The publisher, running on the EC2 box under its instance role, then merges the
bundle into the package's `scripts/` folder:

```
Mac (box.py presign) --SSM--> EC2 box: presign_put.py --> s3 _state/pmp/presign/<run>.json --(AWS_PROFILE=bim)--> Mac --> Modal jobs
Modal: bundle_lib.make_bundle + upload_bundle --PUT URL--> s3 _state/pmp/bundles/<run>/<model_id>.tar.gz
Mac (box.py publish) --SSM--> EC2 box: publisher.py --> s3 dataset/packages/3d_partial/<pid>/scripts/...   (+ log _state/pmp/publish/<run>.jsonl)
```

The Mac never writes to `bim-proprietary-data`. It only runs SSM commands, using profile `annotationprod-publish`
as `/tmp/z3c/ssmcli.sh` does. Code reaches the box inside those SSM commands, in chunks, with a sha256 check. It does
not go through S3. The Mac's only S3 access is reading with `AWS_PROFILE=bim`.

| file | runs on | what |
|---|---|---|
| `bundle_lib.py` | Modal + box + Mac (stdlib only, py>=3.9) | the bundle contract: `make_bundle`, `verify_bundle`, `upload_bundle`, `redact_url` |
| `presign_put.py` | box (`/opt/pm/venv/bin/python`, boto3) | one PUT URL per (run, model_id) -> `_state/pmp/presign/<run>.json` |
| `publisher.py` | box | verify + merge bundles into `<target>/<pid>/scripts/`, regenerate `scripts/scripts_manifest.jsonl`, log |
| `box.py` | Mac | `deploy`, `presign`, `publish`, `fakepkg`, `status`, `clean-test` over SSM |
| `tests/test_bundle_lib.py` | Mac | contract unit tests (29 cases: traversal, symlink, tamper, layout, determinism, upload retry/refusal against a local fake endpoint ...) |
| `tests/test_guards.py` | box (`box.py deploy --with-tests`) | write/delete guard matrix, S3 metadata size, `--expect` parsing |
| `tests/basic_fake.py` | Mac -> box | the basic test from a CLEAN test state: presign 1 URL, curl PUT, dry run, real publish to the FAKE target, re-run |
| `tests/e2e_fake.py` | Mac -> box | continues from basic_fake's state: merge, conflicts, idempotency, crash, lock, expiry (14 steps) |
| `tests/verify_published.py` | Mac (read-only) | download a published `scripts/` tree and check it against its `scripts_manifest.jsonl` |

## Bundle contract `pmp-bundle/1` (the Modal app MUST produce bundles with `bundle_lib.make_bundle`)

```python
import bundle_lib as BL
info = BL.make_bundle(
    scripts_dir,                      # local folder that IS scripts/: README.md requirements.txt steelbuild.py issues_lib.py <model_folder>/
    out_path,                         # .../<model_id>.tar.gz
    header=dict(run=RUN, model_id=MID, pid=PID, model_folder=MF, step_relpath='model/step/X.step',
                step_source='ifc'|'db1'|'sds2', code_version='<pipeline/app code version>'),
    sources=lambda rel: '<provenance of scripts/<rel>>',      # or a dict; every file needs one (<= 512 chars)
    code_versions=None)               # optional per-file versions (default header code_version; <= 128 chars)
# -> dict(sha256, bytes, n_files, md5_b64, header, warnings); raises BL.BundleError(code, message) when the publisher would refuse it
r = BL.upload_bundle(out_path, put_url)  # plain PUT; checks the response ETag == MD5 of the body (mismatch: retried, then raises);
                                         # retries network errors, 5xx and transfer 400s (RequestTimeout, IncompleteBody, BadDigest);
                                         # 403/404/405 and other 400s (expired / invalid URL) raise at once
# record info['sha256'] in the Modal index -> publisher --expect checks it
```

Tar contents: `bundle.json` (header + `n_files`, `bytes`, `rows_sha256`), then `scripts_manifest_rows.jsonl` (one row per
file: `path` relative to the package folder, i.e. `scripts/...`, plus `bytes`, `sha256`, `model_id`, `source`,
`code_version`), then the `scripts/` files. Everything in the tar is normalised (mtime 0, uid 0, mode 0644, gzip mtime 0),
so the same inputs always give a byte-identical bundle. `verify_bundle` refuses a bundle that has any of these:

- an absolute path, `..`, a backslash, control characters, or leading/trailing whitespace in a name; a hidden, `__pycache__`, `.pyc` or `.tmp` file
- a symlink, hardlink or device; a duplicate member; names that differ only in case
- a corrupt or truncated gzip; more than 20k files, a file over 1.5 GB, or more than 4 GB in total
- a file without a row, a row without a file, or a row whose bytes or sha256 do not match; rows out of order;
  a `rows_sha256` or `n_files`/`bytes` that does not match
- a header that does not match the S3 key (run, model_id), or a bundle sha256 that differs from `--expect`
- layout problems:
  - any file outside `scripts/`
  - a second model folder
  - `scripts/scripts_manifest.jsonl` inside the bundle (only the publisher writes it)
  - a shared file other than the 4 named ones, or one of those 4 missing
  - in the model folder, a top-level entry other than `build_model.py`, `build_issues_model.py`, `model_info.json`,
    `schedules/`, `verification/`, `issues/`, `source/`
  - a missing required file: `build_model.py`, `build_issues_model.py`, `model_info.json`, `schedules/parts.csv`,
    `schedules/issues.json`, `schedules/missing_parts.json`, `verification/verification.csv`, `issues/WHERE_TO_LOOK.md`,
    `source/provenance.json`
  - not exactly one `issues/*_ISSUES_highlighted.step`
  - a `missing_parts.json` that lists parts while `issues/*_MISSING_parts_only.step` is absent
  - a db1/sds2 model whose `source/` has no `*.ifc`, `*.ifczip` or `*.ifc.gz`
  - JSON that does not parse

`--lenient-layout` turns layout problems into warnings. It never relaxes the safety or integrity checks.
`MODEL_REQUIRED` and `MODEL_TOP_ALLOWED` at the top of `bundle_lib.py` are the single place to change the layout.

## Pre-signed PUT URLs (`presign_put.py`)

- The box reads its role credentials directly from IMDSv2, so it knows their exact `Expiration`.
- A SigV4 URL dies when the credentials that signed it expire. So `X-Amz-Expires = Expiration - now - 120 s`, capped at 7 days.
- In practice that is about 5-6 h. The role rotates its credentials about every hour, and each new set lasts about 6 h.
- It refuses to sign when less than `--min-valid-minutes` (default 60) is left. Then try again after the next rotation.
- Generate the URLs per batch, right before submitting that batch to Modal.
- S3 refuses unsigned `Content-MD5` and `x-amz-*` headers on these URLs, so the uploader sends a plain PUT and checks the ETag.
- The URL file `_state/pmp/presign/<run>.json` maps model_id to {key, url}. It is overwritten on each presign of that run.
- On the Mac the file is saved with mode 0600. Neither tool prints URLs, and `bundle_lib.redact_url` strips the query
  string from every error message.

```
python3 publish/box.py deploy [--with-tests]
python3 publish/box.py presign --run R --ids-file jobs/new5.jsonl          # -> publish/presigned/R.json (0600)
```

## Publishing (`publisher.py`, on the box)

```
python3 publish/box.py publish --run R --target packages --allow-pids new5.json --dry-run    # plan only
python3 publish/box.py publish --run R --target packages --allow-pids new5.json              # for real
    [--expect index.jsonl] [--models ID,ID] [--recheck] [--allow-update] [--lenient-layout] [--detach]
```

- **Targets.** `--target packages` writes to `cad-disk-extract/dataset/packages/3d_partial/<pid>/scripts/`. It requires
  `--allow-pids FILE` (a JSON list of pids or of `{"pid":..}` objects, e.g. `new5.json`, or text lines), or the explicit
  `--all-pids` for a future scale run. `--target fake` writes to `cad-disk-extract/_state/pmp/fakepkg/<pid>/scripts/`
  and is used by the tests. Create a fake package with `box.py fakepkg --pid PID`, which copies the real
  `manifest.jsonl` and `project.json`.
- **Write guard (`Store.put`).** The only keys the publisher can write are `_state/pmp/publish/...` and
  `<target root><allowed pid>/scripts/<something>`. Keys containing `''`, `.` or `..` path segments are refused. A dry
  run can write only `_state/pmp/publish/...`. The publisher deletes nothing except its own lock files.
- **Per package.** The package is locked (`_state/pmp/publish/locks/<target>/<sha1(pid)>.lock`, conditional
  `If-None-Match` put). The package's `manifest.jsonl` must contain the model (model_id + `step_relpath`, and the same
  `step_source`). The current `scripts/` tree is read:
  - the sha256 of each object comes from the state cache `_state/pmp/publish/state/...` when its ETag and size are
    unchanged, otherwise from a HEAD of the object's `x-amz-meta-pmp-*`;
  - S3's own `ChecksumSHA256` is cross-checked;
  - an object without publisher metadata is foreign, and the whole package is refused.
- **Planning.** All checks run before the first write:
  - every shared file must match byte for byte, else `shared_file_conflict`;
  - a model folder belongs to exactly one model_id (`model_folder_taken`, `model_in_other_folder`);
  - a changed file in the model's own folder is refused (`model_file_differs`) unless `--allow-update`;
  - an update that would need a delete is refused (`would_need_delete`), because the publisher never deletes;
  - a file whose `x-amz-meta-pmp-*` would exceed S3's 2 KB user-metadata limit is refused (`metadata_too_large`) before
    any upload, instead of failing half-way through a package (only very long, heavily percent-encoded `source` strings).
- **Writing.** Upload order is the model-folder files, then any new shared files. Each object carries
  `x-amz-meta-pmp-{sha256,model-id,run,source,code-version,bundle-sha256}` and `ChecksumSHA256`, so S3 rejects a
  corrupted body. The tree is then re-listed and `scripts/scripts_manifest.jsonl` is **regenerated from the tree**.
  It is written with a conditional put on the previous manifest's ETag, and only when its content changes.
  - Manifest rows: `path`, `bytes`, `sha256`, `model_id` (null for the 4 shared files), `source`, `code_version`, `run`; sorted by path.
  - The manifest is the commit record and is written last. An interrupted publish leaves files that are not yet listed.
    The next run recognises them by their sha256 metadata and completes the publish (tested: crash after 3 uploads, then
    a re-run that uploads 8 and skips 7).
- **Proof and log.** The package is listed again, and every object outside `scripts/` must have the same key, ETag and
  size as before (`outside_unchanged`). One record per bundle, plus an invocation summary, is appended to
  `_state/pmp/publish/<run>.jsonl` (`<run>.dryrun.jsonl` for a dry run, which also writes the would-be manifests to
  `_state/pmp/publish/dryrun/<run>/`).
- **Idempotent re-runs.** A bundle the log records as `published` with the same key and ETag is reported as
  `already_published` and not downloaded again. `--recheck` re-verifies it: every file is skipped and the manifest is
  not rewritten.
- **`--expect FILE`** (recommended for real runs): the Modal index `/vol/index/<run>.jsonl` (rows with `bundle.sha256`
  / `upload.bundle_sha256`) or plain rows `{model_id, bundle_sha256}`. Every bundle must match its expected sha256;
  a bundle of a model the index has no sha for is refused (`not_in_expect`); a file with no bundle sha at all, or two
  different shas for one model, stops the publisher before anything is read.
- **Exit codes and statuses.** Exit 0 means every bundle is published, already published or would publish; 2 means some
  were refused; 1 means errors. Statuses: `published`, `already_published`, `would_publish`, `would_skip_identical`,
  `refused` (with `reason` + `detail` + `conflicts`), `error` (with `reason` + `trace`).

## Tests run (2026-10-08 UTC, see `logs/`)

1. `python3 publish/tests/test_bundle_lib.py`: contract unit tests on the Mac (Python 3.9, 3.12 and 3.14).
2. `python3 publish/box.py deploy --with-tests`: write-guard matrix on the box.
3. `python3 publish/tests/basic_fake.py` (21 checks, `logs/basic_fake_results.json`): from a clean test state, presign 1
   URL, `curl` PUT a tiny labelled test bundle into `_state/pmp/bundles/test/` (the URL goes to curl on stdin), run the
   publisher with `--dry-run` (nothing written under the fake `scripts/`) and then for real against
   `_state/pmp/fakepkg/<n4 pid>/`, check it read-only from the Mac with `tests/verify_published.py`, re-run
   (`already_published`, manifest not rewritten), and check the 5 REAL packages are unchanged.
4. `python3 publish/tests/e2e_fake.py`: 14 steps covering idempotency, `--recheck`, a second model merge, shared-file
   conflict, folder takeover, model not in the package, a tampered bundle, `--allow-update`, `would_need_delete`, a
   crash followed by completion, a held lock, an expired URL, the fake package outside `scripts/` unchanged, and the 5
   REAL packages unchanged. Results are in `logs/e2e_fake_results.json`.

`python3 publish/box.py clean-test` deletes only the test state under `_state/pmp/` (run `test`, fake target).

## Known limit for the scale run: mixed-source packages and `scripts/steelbuild.py`

`scripts/steelbuild.py` is a shared file, so it must be byte-identical for every model of a package. The app ships
`code/<variant>/kit/steelbuild.py`, and the three variants differ: `code_v9a` (IFC), `code_db1b` (adds T profiles and
the `kernel_unbuilt` rule) and `code_sds2`. 505 of the 2,418 partial packages mix sources (417 db1+ifc, 74 ifc+sds2,
12 db1+ifc+sds2, 2 db1+sds2). In those packages the publisher will publish the first model and refuse every model of
another variant with `shared_file_conflict`, by design: it never overwrites a shared file. n3's package is one of them
(3 ifc + 1 db1), but only n3 itself (ifc) is published in the 5-sample test, so the test does not hit it. Before
scaling, the app must ship ONE steelbuild.py that builds every variant identically (verified), or the layout must give
the variants different file names.
