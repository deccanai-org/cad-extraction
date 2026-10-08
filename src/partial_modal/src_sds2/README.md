# src_sds2 - SDS/2 -> IFC source stage (Modal app `pmp-src-sds2`)

For every SDS/2-converted model of the partial tier (4,379 rows in projects_p1.json), this stage produces the model's
faithful source IFC. It re-runs the exact converter build that wrote the shipped STEP on the packaged SDS/2 job, and it
proves the result twice:
- the STEP it writes is byte-identical to the shipped STEP (apart from the FILE_NAME time stamp);
- the emitted IFC reproduces the shipped STEP instance by instance.

It also writes `sds2_facts.json`, the converter's side tables, which the issue maker uses to colour parts and to draw
red (missing) parts.

The IFC is emitted from the converter's own in-memory shapes, so the proof is a consistency check against our converter
and not an independent source. Every `provenance.json` says so.

## Files

| path | what |
|---|---|
| `modal_sds2.py` | Modal app `pmp-src-sds2`: image `sds2_image()`, function `sds2_source(job, cls, budget_s)`, `call_for_class()`, unit-test entrypoint |
| `stage.py` | `run(job, ctx) -> dict`: the stage itself (standard library only). This is the plug-in contract of `app/`: `ctx` has `work`, `out`, `log`, `J`, `deadline`, optional `fetch` |
| `pin.py` | `resolve_pin(manifest_row, result_json=None)`: which converter build wrote the shipped STEP (evidence order below) |
| `converters.json` | converter label -> zip + sha256 for all 19 labels the partial tier uses (each checked against a fleet result JSON) |
| `converters/` | the 18 converter zips, byte-exact copies of `/Users/dhiren/Downloads/Deccan/z3conv/sds2_v5/`, plus `SHA256SUMS` (210 MB) |
| `emitter/sds2ifc.py`, `emitter/sds2label.py` | the published IFC emitter 1.1, **unchanged** (sha256 71f36fa8… / 189f1c4a…; 97/97 perfect-tier models proven with it) |
| `emitter/emit_run.py` | runs `decode/sds2_to_step.py JOB -o OUT --stage 2 --verify` with the emitter hooks and the facts hooks, keeping the converter's exit code |
| `emitter/facts_hooks.py` | hooks that run after the converter has written what they read: `_facts_instances.jsonl` and `_facts_convert.json` |
| `facts_build.py` | merges the converter's `_pieces.csv` / `_skipped.csv` / `_manifest.json`, the emitter rows and the hook outputs into `sds2_facts.json` |
| `proofkit/prove_labels.py` | per-instance proof in the pipeline env (based on `nonifc/sds2_emitter/prove.py`, same references and tolerances, plus a full per-instance table and an IFC Name == STEP label check) |
| `proofkit/code_sds2/` | the pipeline's `code_sds2` (tools + kit) used by the proof (`verify.source_props`, `occstep.delivered_props`) |
| `env/conv_requirements.txt`, `env/pipe_requirements.txt` | converter env (py3.12) and pipeline env (py3.11, the fleet's pins) |
| `tests/make_test_job.py` | builds the n5 unit-test job: manifest row, pin, 24 h GET URLs. Run with `AWS_PROFILE=bim`. Only new5.json samples are accepted |

## Job contract (input)

`stage.adapt_job()` also accepts the jobs component's rows and the app's normalised jobs (`common.normalise_job`). It
maps them as follows, and explicit keys always win:
- `conv.step_key` -> `step_key`
- `pin{label, zip, zip_sha256, run, converter}` -> `converter_pin` (basis `job_pin:<run>`, cross-checked against
  `pin.py`; a disagreement fails as `pin_conflict`) and `converter`
- `step{}` / `step_info{}` -> `step_sha256`, `bytes`
- `source{}` / `source_info{}` -> `sds2_sha256`, `sds2_bytes`, `converted_from`
- `urls.source` -> `urls.sds2`

n5 was proven both ways (tests/RESULTS.md).

`id` (or `model_id`), `bytes` (shipped STEP bytes), `step_sha256`, `step_key` (or `source_key`), `converted_from`,
`sds2_bytes`, `sds2_sha256`, `converter` (manifest `{code, version}`), `converter_pin` (`{label, zip, sha256, basis}`
from `pin.py`; if it is absent, the stage resolves the pin itself from the step_key / version and `urls.sds2_result`),
optional `partial` (the manifest's partial record, copied into the facts), and `urls`:
- `step`: shipped STEP
- `sds2`: the package's `model/sds2/*.zip`
- `sds2_result` (optional): the fleet result JSON

The URLs are pre-signed GET URLs (read-only IAM user). They are never logged or written out; only their bucket/key is.

## Pinning the converter (`pin.py`)

The first rule that applies wins:
1. **`conversion_result`**: the fleet result JSON's `step.key` equals the shipped `step_key`. Its `converter` is the
   build that wrote exactly that object.
2. **`r2_run`**: the step_key is under `cad-disk-extract/sds2-step-r2-20260929-01/`, so the build is v4-candidate.
   A result JSON for such a model describes a later re-run that was **not** shipped. For n5 the result says v5.5.0;
   that is recorded in `checks` and not used.
3. **`label_table`**: `converter.version`, which must agree with the step_key's `/<label>/` folder when there is one,
   looked up in `converters.json`.

The pinned zip's sha256 is checked again in the container on every run. The byte-identical re-run is the final proof.

Label -> zip: v4 -> v4-candidate; v5.5.6 and v5.5.6.1 -> v5.5.6.zip; v5.5.11 -> v5.5.11-rc4.zip; every other label ->
`sds2-step-pipeline-<label>.zip`. Partial-tier rows per label: v5.5.11 1748, v4 645, v5.5.9 428, v5.5.7 390,
v5.5.6.1 324, v5.5.3 274, v5.5.0 118, v5.4.1 113, v5.5.8 97, v5.1 84, v5.3 41, v5.4 29, v5.5.5 29, v5.5.4 17,
v5.5.6 16, v5.2 14, v5.5.11-rc3 8, v5 3, v5.5.10-rc 1.

## What one run does (`stage.run`)

1. **pin**: as above.
2. **fetch**: the shipped STEP and the SDS/2 zip. Sizes and sha256s are checked against the manifest. The zip is
   checked for unsafe member paths.
3. **convert**: the pinned converter runs on the job folder, which is linked under the shipped STEP's root product name
   (the job folder name the fleet converted), with
   `decode/sds2_to_step.py JOB -o <step_key basename> --stage 2 --verify`. It uses `/opt/conv` (py3.12 + the
   converters' pins) and `MPLBACKEND=Agg`, without `LD_LIBRARY_PATH`. The emitter and facts hooks are installed.
4. **compare**: the file is byte-identical below FILE_NAME, and FILE_NAME is equal with its time stamp blanked
   (`step_identical`). If not: verdict `step_not_reproduced` and no IFC.
5. **emit check**: every instance is emitted, nothing is unsupported, there are no hook errors, and the IFC sha256
   matches the emitter's report. If not: `emit_incomplete` / `emit_failed`.
6. **prove**: `prove_labels.py` in `/opt/pipe` checks that the two sides have the same id set, that every part is
   within TOL_SRC (volume 1e-3 relative, centre 0.05 mm, bbox 0.05 mm), and that the IFC Name equals the STEP label.
   If not: `ifc_not_reproduced`.
7. **facts**: `sds2_facts.json`.

Outputs, only when all of the above pass:

```
model.ifc            IFC4. GlobalId = sds2label.guid(sha256 of the shipped STEP, instance label); deterministic bytes
provenance.json      converter pin + basis + checks, re-run proof, emitter (+ sha256 of every hook file), reproduction
                     summary, inputs (bucket/key, bytes, sha256), per-step seconds, environment (both pip freezes)
sds2_facts.json      see below
reproduction.csv.gz  one row per id: guid, label, in_step, in_ifc, ifc_name, source_kind, vol_rel, centroid_mm,
                     bbox_mm, ok, why
converter/           the converter's own pieces.csv, skipped.csv, manifest.json (v5.x only), preview.png,
                     plus convert.log, prove.log, ifc_emit.json, ifc_products.jsonl
```

On failure, the outputs are `provenance.json` (ok false, verdict, the evidence) and `converter/`.

On Modal, the outputs go to the volume `pmp-out`:
- success: `/<model_id>/source/` (replaced atomically)
- failure: `/<model_id>/logs/src_sds2_failed/`
- every run: `/<model_id>/logs/src_sds2.log` and `/<model_id>/logs/src_sds2_result.json`

## `sds2_facts.json` (schema `pmp-sds2-facts/1`)

All coordinates are world mm of the shipped STEP. SDS/2 inch values are named `*_in`.

- **`instances[]`**: one row per top-level STEP instance, in document order.
  - `guid` is the pipeline's part id.
  - Identity: `label`, `part` (unique part number), `ifc_class`, plus `member`, `member_type`, `piece`, `inst` and
    `name` parsed from the label.
  - From the converter's pieces.csv row: `kind`, `builder`, `standin` (v5.x text), `also_on_member`.
  - `category`: exact | sds2_bolt | nominal_bolt | member_envelope | joist_envelope | joist_standin | concrete_prism |
    turned_primitive | approximated | flagged_exact | unknown. It is derived only from what the converter recorded,
    never a colour (definitions in the `facts_build.py` docstring).
  - Geometry: `origin_mm`, `x`, `z` (placement), `bbox_mm`.
  - `holes`: the tools the converter actually cut, in world mm: `[kind, start xyz, axis xyz, radius, length
    (, slot half-length)]`.
  - `bolt`: `{source sds2|nominal, dia_in, grip_in, length_in, type}`.
  - `label_approx_note`: v5.x `[approx: ...]`.
  - `grating_name`.
- **`skipped[]`**: the pieces the converter did not write (its `_skipped.csv`: member, piece, inst, name, kind, reason,
  origin in inches), each with `source_evidence`:
  - the piece-table record (name, section index, L/W/T in, weight in lb, L x W x T steel weight for plates);
  - section dimensions;
  - the placement found in the member file by its origin (origin mm + rotation rows; world = origin + M.T @ local);
  - the piece's own vertices (local bbox, world bbox, and all world points when there are <= 512);
  - the member's work line.

  A piece rejected for its vertices (e.g. `fallback_over_5x_source_weight`) may hold corrupt vertices; the piece-table
  size is the other source record.
  - `geometry` (RED part for the issue maker, the shape `make_issues.sds2_missing` reads): `{kind: prism_world,
    outline_world (mm), normal, thickness (mm), offset 0, what, basis}`: the convex hull of the piece's own vertex
    records on its two largest local axes, extruded over their range along the thinnest one, placed by the member-file
    placement. It is given ONLY when (1) the placement is orthonormal, the extents are not degenerate and the vertices
    lie inside the model's parts box + 2 m, and (2) a second source record confirms it: the name's `D x W` designation
    (`GR1 1/2x35 13/16`, `PL3/8x6`) equals thickness and one in-plane extent within 1/16 in, or the piece-table L x W x T
    equals the three extents within 1/16 in, or the envelope's steel weight is 0.67-1.5 x the piece-table weight.
    Otherwise `geometry` is null and `geometry_withheld` says why (the issue maker then draws a labelled marker at the
    recorded origin). `bbox` = `[xmin, ymin, zmin, xmax, ymax, zmax]` mm of the prism. `geometry_checks` holds every
    check (weight ratio, name dims, piece-table L/W/T, member work-line length vs the long extent, confirmed_by).
  - A bar grating's `what` says it is the solid envelope of the panel and that the bars are not modelled (SDS/2 weighs
    the open mesh, so the envelope is about 5-7 x heavier: that is why the converter's 5x rule skipped it).
- **`members_without_geometry[]`**: members (not Ref Point) with no row in pieces.csv or skipped.csv, so the converter
  wrote nothing for them. Each has its work line `p1_mm` -> `p2_mm` and its section with dimensions.
- **`members[]`**: every member of the job (id, type, work line, roll, section), usable as landmarks.
- **`standin_groups[]`**: non-exact instances grouped by category / builder / name, with their guids.
- **`counts`**: `by_category`, `by_builder`, `by_ifc_class`, `bolts_sds2` / `bolts_nominal`, `skipped`, `skipped_with_geometry` and
  `skipped_by_reason`, `members_without_geometry`, cut-hole tools, decoded holes.
- Converter context: `holes_by_piece` (holes decoded from the piece files), `converter_stats` (convert()'s stats),
  `converter_manifest` (v5.x `_manifest.json`, verbatim), `partial_record` (the package manifest's), `errors`, `notes`.

## Images and resources

`sds2_image()`:
- debian-slim py3.12 and the OCC system libs;
- `/opt/conv`: py3.12 venv with `cadquery-ocp==8.0.1.0.0 numpy==2.5.3 scipy==1.18.1 shapely==2.1.2 matplotlib==3.11.2`;
- `/opt/pipe`: a uv 0.12.14-managed py3.11 venv with the fleet requirements (build123d 0.13.0, cadquery-ocp-novtk
  8.0.1.1.0, ifcopenshell 0.9.0, ...);
- the converter zips at `/opt/sds2_converters` (sha256-checked at build);
- the code at `/pmp/src_sds2`.

Resources by size class (`RES` in `modal_sds2.py`, applied with `.with_options()` by `call_for_class`):

| class | cpu | memory | timeout | proof jobs |
|---|---|---|---|---|
| S | 2 | 8 GiB | 2 h | 4 |
| M | 4 | 16 GiB | 4 h | 8 |
| L | 8 | 32 GiB | 8 h | 16 |
| XL | 16 | 64 GiB | 16 h | 32 |

- Models of 1 GB or more are refused as `too_big_v1`.
- `max_containers=10`.
- Modal retries container failures once. A stage failure is a returned result with `ok: false` and is never retried.

## Use

```
# unit test (new sample n5 only)
AWS_PROFILE=bim .venv/bin/python src_sds2/tests/make_test_job.py <scratch>/job_n5.json      # 24 h GET URLs; keep out of the repo
.venv/bin/modal run src_sds2/modal_sds2.py --job-file <scratch>/job_n5.json --result-file <scratch>/result_n5.json

# from the app
from src_sds2.modal_sds2 import sds2_image, call_for_class, RES       # same image in the app, or:
fn = modal.Function.from_name('pmp-src-sds2', 'sds2_source')          # after: modal deploy src_sds2/modal_sds2.py
rec = call_for_class(fn, job)                                         # -> /vol/<id>/source/ on pmp-out
# or, as a plug-in inside an image built with sds2_image(): sys.path.insert(0, '/pmp/src_sds2'); import stage; stage.run(job, ctx)
```

The pipeline then runs code_sds2 on `source/model.ifc` (the emitter's FILE_NAME originating system switches on SDS/2
mode). The package step publishes `source/provenance.json` and `model.ifc`, renamed as the layout wants, into
`scripts/<model_folder>/source/`.

## Test result

n5 on Modal: reproduced (byte-identical STEP, 645/645 instances), 3 of 3 skipped gratings with confirmed geometry,
outputs identical across runs. Details in `tests/RESULTS.md`.
