# src_db1 - DB1 -> faithful source IFC (Modal stage)

For a DB1-sourced partial-tier model (Tekla `.db1` in `model/db1/`, or in `dataset/packages/3d/<pid>/model/db1/` for add-ons)
this stage regenerates the IFC our decoder produced when it converted the model, PROVES it is that IFC (its STEP equals the
shipped STEP line for line, PRODUCT ids included), restores the shipped GlobalIds, and exports what the DB1 holds for every
part the conversion skipped or approximated (`skipped_records.json`, for the RED / ORANGE parts of the issue model).

Unit tests (Modal, new samples only): **n1** (`992c3de4...`, engine 7.82, S) and **n2** (`4d188bba...`, the add-on, engine
6.87 old-engine path, M) both `reproduced` with kit_v / profile x86-64-v4; see "Test results".

## Host requirement: AVX-512 (found 2026-10-07)

The numbers the decoder and the STEP stage write depend on the numeric kernels numpy / OpenBLAS dispatch for the host CPU.
`tests/diag_cpu_repro.py` ran kit_v on n1 in 6 containers under kernel variants (`tests/results/diag_cpu_repro.json`):

| host | numpy dispatch | OpenBLAS core | STEP vs shipped |
|---|---|---|---|
| Intel Skylake-SP (6/85), AMD Zen 4 (25/17) | X86_V3, X86_V4 (+AVX512_ICL) | SkylakeX | **identical** |
| same hosts, `NPY_DISABLE_CPU_FEATURES=X86_V4 ...` | X86_V3 | any | 9,603 lines differ |
| AMD Zen 3 (25/1), no AVX-512 | X86_V3 | Haswell | 9,603 lines differ (every variant) |

The STEP stage's output follows numpy's AVX-512 dispatch; the decoder's IFC numbers follow the OpenBLAS core (Haswell vs
SkylakeX kernels give different IFC bytes but the same STEP for n1). The earlier "Debian glibc" explanation was wrong: the
first n1 mismatch (`tests/results/n1_db1_small.debian_image_mismatch.json`) was an AVX2 host.

So:
- `stage.py` checks the CPU first (`cpu_facts.py`; no download on a bad host). No AVX-512 (F, CD, BW, DQ, VL) ->
  verdict `host_unsuitable`, `retryable: true`, nothing written but logs.
- `regen_core.py` pins the kernels per **CPU numeric profile** (set for the decoder, the STEP stage and db1_facts.py):
  - `x86-64-v4` = `OPENBLAS_CORETYPE=SkylakeX`, `NPY_DISABLE_CPU_FEATURES=AVX512_SPR`: an AVX-512 conversion host (tried first)
  - `x86-64-v3` = `OPENBLAS_CORETYPE=Haswell`, `NPY_DISABLE_CPU_FEATURES=X86_V4 AVX512_ICL AVX512_SPR`: an AVX2-only
    conversion host, emulated on the AVX-512 host (the diagnostic shows this reproduces the AVX2 hosts' bytes).
  Pinned, the bytes do not depend on the host model: n1's `model.ifc` sha256 `3a12d0ed...` is identical on Intel Skylake-SP,
  Intel Ice Lake (6/106) and AMD Zen 4 (8 runs, AWS / Azure, 4 regions).
- Placement: Modal refuses `cloud=` pinning in this workspace ("Pinning cloud aws/gcp not supported") but accepts
  `region=`. Unpinned, ~1/3 of fresh containers are AVX-512 (`tests/results/cpu_census.json`) and sequential retries are
  correlated (n2 needed 16 draws). `region='ap-southeast'` (the conversion fleet's own region) gave 8 AVX-512 hosts in 9
  draws. Modal bills region-pinned functions at a premium - owner's decision; `PMP_DB1_REGION=ap-southeast` enables it in
  `modal_src_db1.py` (default: unpinned).

## What runs (container)

1. `stage.py` (Modal's python, standard library only): host gate; downloads from pre-signed GET URLs (never logged; only
   bucket/key): the DB1 (sha256 must equal the model id), the delivered package STEP (bytes + sha256 from the job), and,
   when the job has them, the conversion fleet's `results/<id>.json`, `<id>.u.src_parts.jsonl.gz` (per-product census of
   its IFC) and `<id>.decoded_parts.json.gz`. URL names accepted: `db1|source|src`, `step`,
   `results_json|detail/results_json`, `src_parts|detail/src_parts`, `decoded_parts|detail/decoded_parts`
   (`detail/<alias>` = jobs/presign.py naming).
2. `regen_core.py` (conda env python; = the bench `db1_regen/scripts/regen.py` that reproduced 171/171 models, packaged):
   - kit choice from the shipped STEP's `FILE_NAME` (writer `ifc2step6 6.1.7` + write time): written after the code-v deploy
     (2026-10-05T22:46Z) -> `kit_v` first, before -> `kit_u` first; the other kit is tried when the first does not
     reproduce. Any other writer (code q = `ifc2step6 6.1.5`, kit not packaged) -> `refused` (`kit_lost: ...`). STEPs the
     fleet produced through its crash rescue (`rescue` / `unholed_elements` / `excluded_elements` in the result JSON) ->
     `refused`. Kit files md5-checked against `KIT.json` (= the S3 version-history manifests in `kit_manifests/`); the
     catalog overlay md5 is compared with the one the result JSON records (`catalog_overlay_check`).
   - attempts in order (kit, profile): (pinned, v4), (pinned, v3), (other, v4), (other, v3); stops at the first
     reproduction, or when the stage deadline leaves no time for another attempt (`attempts_not_run`).
   - per attempt: `convert_one.py in.db1 model.ifc ...` (+ full discovery when the fast path defers, as the worker did),
     `ifc2step6.py model.ifc model.stp --mode hybrid --prec 2 --threads 4` (venv ifcopenshell 0.8.4.post1; OCC read-back
     verifier = conda env pythonocc-core 8.0.1); `stepcmp.py`: regenerated STEP == shipped STEP line for line after
     canonical #-renumbering (FILE_NAME not compared), PRODUCT ids aligned -> GlobalId map (bijection).
   - restore: product GlobalIds <- the shipped ones (text substitution on IfcRoot lines only); IfcRoot entities without a
     STEP product get `compress(sha256("<id>:<entity id>")[:32])`; IFC header / OwnerHistory times := shipped STEP
     FILE_NAME time (determinism). The restored IFC is converted again: its STEP must equal the shipped STEP INCLUDING every
     PRODUCT id -> `reproduced`. Census cross-check against the fleet's `src_parts` (gid, class, name per product).
3. `db1_facts.py` (decoder venv, same profile) re-runs the same kit's converter in-process with `sys.settrace` capturing the
   converter's own local state at return (no kit file edited, line events off) and writes `skipped_records.json`. It is
   usable only if its parts list equals the reproducing run's AND the fleet's `decoded_parts` (every field but the random
   GlobalId): `usable_for_red_parts`.

## Outputs (Volume `pmp-out`, `/<out_root>/<model_id>/`; plug-in: into `ctx['out']`)

| file | when | deterministic |
|---|---|---|
| `source/model.ifc` | verdict `reproduced` only | yes (same bytes on every AVX-512 host) |
| `source/provenance.json` | always (except host_unsuitable) | yes (no wall times / paths / host facts) |
| `source/skipped_records.json` | whenever the pinned kit decodes the DB1 | yes |
| `logs/src_db1/*` (decoder log, timings, host CPU, decoder stats, per-attempt STEP sidecars, stage result) | always | no |
| `logs/src_db1_host_draws.jsonl` | standalone function: one row per AVX2 container drawn | no |

`provenance.json`: verdict (`reproduced` / `mismatch` / `fail` / `refused` / `host_unsuitable`) + reason, kit (dir, code,
manifest, snapshot, file md5s), engine, `kit_selection`, `attempt_plan`, every attempt (kit, profile, convert stats,
verdict, `catalog_overlay_check`), `cpu_profile` (name, env, meaning), proof (`regenerated_vs_shipped`,
`restored_vs_shipped`: lines, products, diff lines, identical flags), GUID restore stats, time normalisation, census check,
input keys + sha256s, `conversion_result` (code, runtime, started, engine, status, out_key), `ifc` {bytes, sha256},
`skipped_records` summary {sha256, status, usable_for_red_parts, proof, counts, kit, profile}.

### skipped_records.json (schema `pmp.src_db1.skipped_records/1`)

- `status` ok | inconsistent | failed; `usable_for_red_parts`; `proof` {parts_list_vs_reproducing_run,
  parts_list_vs_conversion_fleet, gid_source, gids_vs_conversion_fleet, written_products_in_shipped_step ...}
- `skipped[]`: `record` (DB1 record id), `reason` (converter's: unresolved, contour_plate_no_outline, implausible_profile,
  no_profile, bolt_group_unplaced, bolt_group_excluded ...), `category`, `profile` (profile string), `axis` {O, E, L, x, y,
  z}, `catalog_lookup`, `profile_number_mm` (the converter's own contour-plate thickness rule: first number of the profile
  string - a candidate thickness), `profile_is_bare_number`, `outline_local` / `outline_world` + `outline_source` (DB1
  contour record; contour plates are centred on that plane), `attributes` (ASCII strings with byte offsets / old engines:
  material, name), `cut_bodies_linked`, `bbox_world`, `geometry_recorded` (outline+profile_number | outline | axis+profile
  | axis_only | bolt_positions+axis+diameter+length | none), `bolt_group` for skipped bolt records.
- `dropped_by_step_writer[]`: parts in `model.ifc` (decoder wrote them) whose product the shipped STEP lacks.
- `cut_bodies[]`: record, built, unbuilt_reason, parents (record, written, gid), applied_to; unbuilt: axis + outline.
- `fittings_not_applied[]`: members whose Tekla fittings / line cuts were decoded but not applied: gid, axis, fitting planes.
- `bolt_groups[]`: record, written_as, gid, in_shipped_step, standard, d, L, O/x/y/z, positions_world, plies (record, gid,
  written, slotted), slot {decision: not_slotted | decoded | undecided_holes_cut_round}, flags (nominal head/nut, axial
  unknown / fitted, washers nominal, washer side inferred, tolerance not decoded), bolts[] (centre, axis, d, L, ...).
- `parts[]` = [record, profile, category, status, how_or_reason, gid, in_shipped_step, n_cuts] (`parts_columns`).
- `counts`, `converter_stats` (the converter's own skip / bolt / cut / fitting statistics for cross-checks).
Units mm; world = decoder model coordinates = the IFC / STEP frame (IfcSite placement is the identity).

## Image (`modal_image.build(modal, root)`, used by both the standalone app and the app's plug-in loader)

amazonlinux:2023 (the conversion fleet's OS) + Modal python 3.11 + micromamba env `/opt/conv/env` from
`env/conda_env.lock.txt` (exact name=version=build, 310 packages: python 3.11.17, pythonocc-core 8.0.1, ifcopenshell 0.9.0,
numpy 2.4.6) + venv `/opt/conv/ifc84` from `env/ifc84.requirements.txt` (exact pins, `--no-deps`: ifcopenshell
0.8.4.post1, numpy 2.4.6) + kits `/opt/kits/kit_v`, `/opt/kits/kit_u`. Build gates: `env/check_env.py` (installed == locks,
no OCC in the venv) and `env/check_kits.py` (kit md5 == S3 manifests). No credentials in the image or in Modal secrets.
The component code is mounted at `/pmp/src_db1` (the app copies the folder minus `kits/`, `tests/`).

## Run (standalone app `pmp-src-db1`; only the new DB1 samples n1, n2 are accepted)

```
# unit-test jobs (Mac, read-only IAM user; URLs are written to a 0600 file and never printed)
AWS_PROFILE=bim .venv/bin/python src_db1/make_test_jobs.py --tags n1,n2 --hours 48
.venv/bin/modal run src_db1/modal_src_db1.py::main --env-only                                     # image gates only
.venv/bin/modal run src_db1/modal_src_db1.py::main --jobs src_db1/tests/jobs_n1n2.urls.json --only n1,n2
.venv/bin/modal run src_db1/modal_src_db1.py::main --jobs ... --only n1 --repeat 3 --out-root _unit/src_db1   # cross-host determinism
PMP_DB1_REGION=ap-southeast .venv/bin/modal run src_db1/modal_src_db1.py::main --jobs ... --only n1        # region-pinned
.venv/bin/modal run src_db1/modal_src_db1.py::plugin --tag n1        # app plug-in contract with the jobs component's row
.venv/bin/modal run src_db1/tests/diag_cpu_repro.py --n 6            # CPU diagnostic (n1)
.venv/bin/modal run src_db1/tests/cpu_census.py --n 10               # host CPU census (no data)
```
The `src_db1` function: `single_use_containers=True` (each call / retry is a fresh host draw; without it retries were seen
landing on the same AVX2 container), `retries=10` (Modal's maximum), the entrypoint re-spawns a call that still ends
host-unsuitable (`PMP_DB1_RESPAWNS`, default 2). Results: `src_db1/tests/results/<tag>.json`.

Resources per class (delivered STEP bytes, decimal): S < 10 MB cpu 4 / 16 GiB / 3 h, M < 100 MB 4 / 32 GiB / 10 h,
L < 500 MB 6 / 64 GiB / 20 h, XL < 1 GB 8 / 128 GiB / 24 h; >= 1 GB: `too_big_v1`. Two STEP conversions per attempt, up to
four attempts; measured: n1 (5.7 MB) 26-37 s, 1.6 GiB; n2 (26.8 MB) 84 s, 1.9 GiB.

## App integration (plug-in contract, app/pmpstages/plugins.py)

`stage.run(job, ctx)` writes `model.ifc`, `provenance.json`, `skipped_records.json` into `ctx['out']` and returns
`{ok, error, ifc: 'model.ifc', sha256, provenance, verdict, kit, profile, host_cpu, retryable ...}`.
On an AVX2 host it returns `{'ok': False, 'retryable': True, 'verdict': 'host_unsuitable', 'error': 'host_unsuitable: ...'}`
with `ctx['out']` empty, after `modal.experimental.stop_fetching_inputs()`. What the app has to do (not in app/ yet):
1. re-call the source stage while the result is `retryable` (a new container = a new host draw; budget ~30 calls, or
   fewer with a region pin), recording the draws; never count `host_unsuitable` as a model failure;
2. define its `src_db1_*` functions with `single_use_containers=True` (and `region='ap-southeast'` if the owner accepts the
   premium);
3. not rely on exceptions for this: Modal re-raises a BaseException in the caller (it escapes `except Exception` in
   orchestrate._call), and an Exception raised in `run()` is recorded by `run_plugin` as a final source failure
   (`tests/results/baseexc_retry.json`).
Tested: `modal_src_db1.py::plugin` drives `stage.run(job, ctx)` with the jobs component's signed row normalised by
`app/pmpstages/common.normalise_job` - n1 reproduced, same sha256, AVX2 draws handled
(`tests/results/plugin_n1_db1_small.json`).

## Test results (`tests/results/`)

| file | model | host | verdict | model.ifc sha256 | skipped_records sha256 |
|---|---|---|---|---|---|
| n1_db1_small.json (final code) | n1 | Intel Skylake-SP, AWS ap-southeast | reproduced kit_v / x86-64-v4 | 3a12d0ed... | 02317ed1... |
| n2_db1_addon.json (final code) | n2 | Intel Skylake-SP, AWS ap-southeast | reproduced kit_v / x86-64-v4 | 98292c72... | 182e1ab8... |
| n1_db1_small.unpinned_r1..r3.json | n1 | AMD Zen 4, Azure (after AVX2 draws) | reproduced | 3a12d0ed... (x3) | 02317ed1... (x3) |
| n1_db1_small.region_ap-southeast_r1/r2.json | n1 | Zen 4 / Skylake-SP | reproduced | 3a12d0ed... (x2) | 02317ed1... (x2) |
| plugin_n1_db1_small.json | n1 | Zen 4 after 3 AVX2 draws (plug-in path) | reproduced | 3a12d0ed... | 02317ed1... |
| (earlier run, overwritten) | n1 / n2 | Intel Ice Lake AWS / AMD Zen 4 Azure | reproduced | 3a12d0ed... / 98292c72... | 02317ed1... / 182e1ab8... |
| n1_db1_small.debian_image_mismatch.json | n1 | AVX2 host (before the host gate) | mismatch | - | - |

provenance.json is byte-identical across hosts for the same code (n1: unpinned / region / plug-in runs); the final code adds
`catalog_overlay_check` (kit overlay md5 0394baae... == the conversion record's).
n1 proof: 119,079 STEP lines, 376 products, 0 differing lines; 376 GlobalIds restored, 4 derived; census 376/376.
n2 proof: 544,373 lines, 738 products, 0 differing; 738 GlobalIds restored, 4 derived; census 738/738.
skipped_records vs the partial records: n1 `bolts_in_slotted_groups_cut_round` 14 = "14 hole slotted cut round"; n2 34
parametric gratings, 89 nominal head/nut bolts, 102 nominal washers, 23 inferred washer sides, 126 slotted bolts cut round
= its partial record's five counts exactly. Neither model has skipped records (`skipped: 0`), so they exercise no RED
outline; the outline / thickness path (`skipped[]`) is the bench probe_db1.py logic and is untested on Modal.
