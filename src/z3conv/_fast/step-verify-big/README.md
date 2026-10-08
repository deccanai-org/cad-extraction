# step_verify_big.py: streamed OCC verification of large STEP files

This tool computes the OCC read-back signals that `z3conv/common/step_check.py` produces, for STEP files that the grader
skips today. Those files are tagged `not_read_back_large_file`: either the file is 1 GB or more (`RB_MAX`), or the full
read-back ran out of memory. The tool never loads the whole file into OpenCASCADE.

The output JSON has the same keys and meanings as `step_check.py`'s output, and `--parts` has the same per-root record
format. That means the index builder (`coord/build_index.py: step_checks`) and `grade_join.join` can use it unchanged.
Equivalence with full read-backs is measured in `equiv/box/equiv_p1.json` and `equiv/box/equiv_p2.json`, produced by
`box/equiv_summary.py` on BOX-A.

## How it works

1. **One streaming pass** over the file, in 16 MB buffers.
   - It runs the step_check text pass on the same lines and builds the same maps: `markers`, `schema`, `products`,
     `approx_products`, `v6_tags`, and the PRODUCT <- PDF <- PD <- PDS <- SDR chain.
   - It parses every `#id` occurrence with numpy into definitions and references.
   - It cuts the DATA section into contiguous blocks of about `--chunk-mb`. Each block ends right after a
     `SHAPE_DEFINITION_REPRESENTATION` statement, which is the last statement of every product in ifc2step output.
   - For each block it writes the ids it defines to an on-disk index (`idx_*.npy`) and keeps the ids it references but
     does not define (its external references).
2. **Closure.** The transitive closure of every block's external references is fetched from the file by id. These are
   the header contexts and units, the global DIRECTION cache, and anything else that is shared. Some PDS, SDR or
   `*REPRESENTATION_RELATIONSHIP` statements sit in a different block from the product or representation they attach to.
   Those are attached to the block that holds that product, because OCC finds them through *upward* references.
3. **Chunks.** For each block the tool writes one self-contained Part 21 file:
   - the original HEADER
   - the foreign statements that block needs
   - the block's own statements, verbatim and in original order

   A worker process (`--worker`) reads the chunk with `STEPControl_Reader` and runs step_check's per-root loop:
   `TransferRoot`, solids, shells, faces, `Bnd_Box` (`useTriangulation=False`), `BRepCheck_Analyzer` per solid, and
   GProp volume per solid. Raw floats are returned.
4. **Aggregation.** Roots are collected in the global order of a full read: OCC roots are PRODUCT_DEFINITIONs in file
   order. Each root is counted only in the chunk that holds its PRODUCT_DEFINITION statement; foreign roots pulled in as
   context are ignored. The aggregation then rebuilds:
   - the step_check totals
   - the per-part records: `i`, `pid`, `name`, `desc`, `solids`, `shells`, `faces`, `bbox`, `valid`, `volume`, `empty`,
     `nonfinite`
   - `invalid_examples`
   - the global `bbox`, with `Bnd_Box::Add` semantics: the minimum of raw minima, enlarged by the maximum gap.

   With `--max-check N`, step_check's root sampling is emulated exactly in global root order, using
   `random.Random(7)` and the same short-circuit. The default of `0` checks every solid.
5. **Memory budget.**
   - Workers run in parallel (`--workers`) under `--mem-gb`. That is the budget for this process plus its workers.
   - Memory is measured as phys_footprint on macOS (resident plus compressed plus swapped, which is what Activity
     Monitor shows) and as VmRSS on Linux. Each child is polled every 0.5 s.
   - The per-worker estimate is the measured peak bytes per chunk byte times 1.15.
   - A worker that pushes the whole process tree over budget is killed. The tool retries it alone. If it fails again,
     the tool cuts that block into quarters at SDR boundaries, recursively, down to one product.
   - A single product that still crashes OCC or runs out of memory is reported as a crashed root (`empty` +
     `crashed`), not as a read failure of the whole file.
   - A chunk that does not read (`read_status` other than ok) is re-cut in the same way. If the first 3 chunks all fail and
     none has read, the file itself does not read: `read_status` is that failure, as a full read would report it.

## CLI

```
step_verify_big.py FILE.step OUT.json [--parts OUT.parts.jsonl.gz]
                   [--chunk-mb 24] [--workers 3] [--mem-gb 5] [--rss-per-byte 30]
                   [--max-check 0] [--timeout 14400] [--workdir DIR] [--keep] [--plan-only]
                   [--python PY]
step_verify_big.py --worker CHUNK.step CHUNK.json        # internal, one chunk
```

| option | default | meaning |
|---|---|---|
| `--parts` | none | per-root records (gzip JSONL), same format as `step_check.py --parts` |
| `--chunk-mb` | 24 | target block size in MB of the source file. Worker peak memory is about 20 to 24x the chunk bytes (measured on BOX-A: 24 MB chunks peak at 0.49 to 0.57 GB per worker) |
| `--workers` | 3 | parallel OCC worker processes |
| `--mem-gb` | 5 | memory budget for the whole process tree |
| `--max-check` | 0 | `0` checks every solid (exact, `sampled: false`). `N` emulates step_check's sampling above N estimated solids |
| `--timeout` | 14400 | per-chunk worker timeout in seconds. On timeout the block is cut smaller |
| `--workdir` | temp dir next to OUT | chunk files, index, and `run.log`. Removed at the end unless `--keep` |
| `--plan-only` | off | runs pass 1 and the chunk plan only (no OCC), and reports the chunk sizes and extra statements |
| `--python` | current interpreter | interpreter for the workers. It needs pythonocc-core (`OCC.Core`) or cadquery-ocp (`OCP`) |

Environment: Python 3.11, pythonocc-core 8.0.1, numpy. This is the same kernel as the grader's conda env
(`common/setup_occ.sh` installs the latest pythonocc-core from conda-forge, which is 8.0.1). It is also the agent boxes'
`/opt/conv/env/bin/python`, which ran every measurement here. Do not run the tool on the owner's Mac: `_env/` is a stale
local env from an earlier session.

## Output JSON (OUT.json)

These keys have the same meaning as in step_check:

| key | meaning |
|---|---|
| `file`, `bytes` | basename and size of the STEP file |
| `markers` | counts of `FACETED_BREP`, `POLY_LOOP`, `CLOSED_SHELL`, `OPEN_SHELL`, `MANIFOLD_SOLID_BREP`, `ADVANCED_FACE`, `SHELL_BASED_SURFACE_MODEL`, `TESSELLATED`, `TRIANGULATED_FACE_SET`, `NEXT_ASSEMBLY_USAGE_OCCURRENCE`, `MAPPED_ITEM` (text occurrences) |
| `schema` | first `FILE_SCHEMA` line, up to 200 characters |
| `products`, `approx_products`, `v6_tags` | PRODUCT count, products tagged `[approx:` in id or name, and `[v6:` tag counts from PRODUCT.description |
| `text_sec` | duration of the streaming pass (here: text pass plus block planning) |
| `read_status` | `ok` when every chunk was read by `STEPControl_Reader`, otherwise `fail:chunks N` |
| `roots` | OCC roots, i.e. PRODUCT_DEFINITIONs reported as roots by the workers |
| `check_fraction`, `sampled` | 1.0 / false unless `--max-check` sampling applies |
| `transferred`, `empty_roots` | roots transferred, and roots that were not transferred or gave a null shape. Crashed roots count here too, see `streamed` |
| `solids`, `shells`, `faces` | sums over roots. `shells` is counted only for roots without solids |
| `checked`, `valid`, `invalid` | BRepCheck_Analyzer per solid |
| `nonpos_vol` | solids whose GProp volume is not > 0 |
| `nonfinite` | roots whose bbox is not finite or exceeds 1e10 |
| `valid_solids_est`, `invalid_solids_est`, `invalid_frac` | as step_check. They are equal to the exact counts when nothing is sampled |
| `invalid_examples` | the first 50 `[pid, name]` with an invalid solid, in root order |
| `roots_mapped_to_products` | parts records with a pid or name |
| `bbox` | global `Bnd_Box` (mm, 3 decimals) |
| `occ_sec` | sum of the worker transfer-loop seconds |
| `sec` | total wall-clock seconds |

`streamed` holds the extra fields:

| key | meaning |
|---|---|
| `version`, `kernel` | tool version and OCC kernel |
| `chunk_target_bytes`, `blocks` | target block size and number of blocks |
| `chunks_planned`, `chunks_run`, `chunks_resplit`, `chunks_crashed`, `crashed_chunks[]` | chunk bookkeeping. Each crashed chunk entry has `chunk`, `why`, `bytes`, `log_tail` |
| `crashed_roots`, `roots_without_label`, `pd_not_reported_as_root`, `pd_not_reported_examples`, `chunk_read_failures[]` | completeness checks |
| `complete` | true when no root crashed or failed |
| `exact` | `{checked, valid, invalid, nonpos_vol}` over every solid, even when `--max-check` sampling is emulated |
| `parts_tol_gt_0p1mm` | roots whose healed tolerance (Bnd_Box gap) is above 0.1 mm. These parts carry `tol` in the parts file. See "Kernel non-determinism" under Limits |
| `shared_statements`, `shared_bytes`, `dangling_refs`, `dangling_examples` | the closure store |
| `attachments_moved`, `srr`, `index_disjoint` | attachment and index diagnostics |
| `max_chunk_bytes`, `max_extras_per_chunk` | chunk sizes |
| `workers`, `mem_budget_bytes`, `peak_tree_rss_bytes`, `peak_worker_rss_bytes`, `parent_peak_rss_bytes` | memory. `peak_tree_rss_bytes` is the polled peak of the sum over the tree |
| `occ_wall_sec` | wall-clock seconds of the OCC phase |
| `unsupported` | `assembly` when the file has NAUO (see below) |

### Parts file (`--parts`, gzip JSONL, one line per root in global root order)

The records are the same as step_check's:
- transferred root: `{"i", "pid", "name", "desc", "solids", ["shells" if no solids], "faces", "bbox" | "nonfinite", "valid", "volume"}`
- not-transferred root: `{"i", "pid", "name", "solids": 0, "empty": true}`

Extra fields:
- `"crashed": "rc -11"` on a root whose single-product chunk crashed or ran out of memory
- `"tol": <mm>` on roots whose healed tolerance is above 0.1 mm
- `"nonpos": n` on roots with n solids whose GProp volume is not > 0 (they make up `nonpos_vol`) (since 2026-10-02b)

## Integration in the grader (code owners)

- **Patches (not applied; the code owners apply them):** `integration/grade_worker.patch` (grade kit and final kit:
  `grade/worker.py`) and `integration/ifc_worker.patch` (`ifc/worker.py`). The patched files are in
  `integration/{grade,ifc}/worker.py`.
  - A STEP `>= RB_MAX` gets `step_verify_big.py stp chk --parts parts --workers $SVB_WORKERS --mem-gb $SVB_MEM_GB`
    (defaults 4 and 8) instead of `step_check.py --no-occ`. `v['skipped']` is no longer set, so
    `build_index.step_checks` grades the model `occ_readback` and stops tagging `not_read_back_large_file`.
  - A medium STEP whose step_check is memory-killed twice (`rc == -9`, the existing retry without render included) falls
    back to the same call.
  - `step_verify_big.py` is added to `FILES`. In `grade/worker.py`, `need_bytes` reserves `SVB_MEM_GB + 1` GB, not
    40x the STEP size, for STEP files `>= RB_MAX`.
  - Tested offline on BOX-A with the grade patch (`integration/test/test_check_step.py`, stub S3). File `>= RB_MAX`:
    calls `step_verify_big.py` only. Two simulated memory kills: `step_check`, `step_check`, then `step_verify_big`.
    Normal path: `step_check` only, unchanged. All three paths give the same signals (9987 solids, 13 invalid, 383
    non-positive volumes on m2). The ifc patch mirrors it (syntax-checked).
- **Final pass for already graded models:** `to_final_result.py` builds
  `f-<pipe>-<id[:40]>-readback.json = {status: ok, validate: <OUT.json>, step_parts_key, join}`, with `grade_join.join`
  against the model's `src_parts`. `apply_final` overlays it. The records for the flagged models verified on BOX-A are
  in `s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/step-verify-big/final/{results,detail}/`,
  in the layout of `_state/conv/final/`. Copy them there to apply them. `final/predict.json` gives each model's class
  before and after, computed with a read-only copy of `coord/build_index.py`.
- **Stale records.** A readback record is valid only for the STEP it read (`step_key`). 27 of the 55 models verified
  here have since been re-converted by ifc2step6 (`.v6.step`) and read back normally. Their records are in
  `final_stale/`, kept as evidence only. Unpatched, `apply_final` would overlay them and downgrade, for example, 1093cfd9
  and b9e5ef0a from class 1 to class 2. `integration/build_index_final_pass.patch` makes `apply_final` skip a readback
  whose `step_key` is not the result's current STEP. Apply it before copying any record.
- **Phase 4 (running on BOX-A, nice 19, at most 14 threads).** The CURRENT index's IFC models tagged
  `not_read_back_large_file` / `not_read_back_out_of_memory`, minus those already done: restarted at 01:33Z with 172
  models, 382 GB. Since the index added `openings_volume_unverified` (136 models) and `openings_not_applied` (15), only
  17 (28.8 GB) still have no other blocking issue. Those go first, smallest first, with the join against their src_parts. Each record
  goes to `final/{results,detail}/` as soon as its model is done. Status: `status_p4.json`. Stop:
  `kill $(cat /work/agentwork/step-verify-big/jobq_p4.pid)` and kill its children
  (`pkill -f 'pkg/step_verify_big.py in/Q'`). Spread it over several boxes with
  `box/make_tasks_p4.py INDEX --shard K/N` and `box/run_p4.sh` (one shard per box). At about 1.6 CPU s per MB it is
  about 176 CPU hours: ~3 h on one whole 64-vCPU box, ~15 h at the 12 workers used here (longer while the box is busy, since it runs at nice 19).
- **v6 inventories.** A converter re-run writes its detail with the STEP's suffix (`ifc/detail/<id>.v6.src_parts.jsonl.gz`).
  `detail_keys` looks for `<id>.src_parts.jsonl.gz`, so a final-pass readback of a v6 model gets no join and keeps
  `per_part_verification_pending`. Seen on 1924e526. The same patch fixes `detail_keys`. `make_tasks_p4.py` already
  tries the suffixed key first.
- **Class-1 lifts so far** (`final/predict_now.json`: `classify_ifc` plus the patched `apply_final`, live rules, index
  of 2026-10-02 01:31Z). 1924e526 (v6 STEP, 1.04 GB): 113,518 solids, 0 invalid, gid join coverage 1.0, 11,507 of
  11,507 volumes within 5 %. e21b8fa4 (reused STEP, 933 MB): 48,515 solids, 0 invalid, name join coverage 1.0, 42,919
  of 42,919 volumes within 5 %. Both go from class 2 to class 1 (corpus A). The other 34 applicable records clear
  `not_read_back_large_file` but stay class 2 on real defects: invalid solids, non-positive volumes (90 % in
  IfcMechanicalFastener bolts, `final/nonpos_where.json`), and parts without a solid.
- Render (`render_ink`) is not produced. The final pass still schedules a render when `render_key` is missing.

## Limits

- **Assemblies.** Files with `NEXT_ASSEMBLY_USAGE_OCCURRENCE` are refused: `read_status: null`, a `skipped` message,
  and `streamed.unsupported = assembly`. A root assembly pulls its whole tree, so a per-product cut is not equivalent.
  None of the 186 flagged files has NAUO (all are flat ifc2step products). OCC roots are PRODUCT_DEFINITIONs in product
  mode (`read.step.product.mode` ON, the default).
- **Writers that put SDRs before their geometry.** This includes OCC's own top-down writer. The output is still
  correct, but the work is less efficient: each product's geometry also arrives as extra statements in its PD's chunk.
- **Kernel non-determinism.** On parts that the reader heals heavily, OCC's shape healing is not deterministic, even
  across two runs on the same file. A streamed run can therefore differ from a full run on exactly those parts, by about
  as much as two full runs differ from each other. On BOX-A, 3 full reads of m1 gave 6087 / 6089 / 6090 solids on the
  same file. 7 bolt roots flip between 4, 5 and 6 solids. Every streamed root equals the record of one of the full reads
  (`equiv/box/equiv_p1.json`, `unstable_examples`).

## Measured on BOX-A (r7i.16xlarge, pythonocc 8.0.1, 2026-10-01/02)

Equivalence checks (`box/equiv_summary.py`; evidence in `equiv/box/*.json`):

- **3 medium files, 2 chunk sizes each (2 MB and 24 MB).** m1 is an IFC z3 STEP (53.7 MB), m2 an IFC reused STEP
  (53.0 MB), m3 a DB1 STEP (141.8 MB). Each was compared with 3 full step_check reads on the box plus the grader's
  stored read-back.
  - m2 and m3: identical on every root and every top-level field.
  - m1: 4 of 2162 roots differ. All 4 are roots on which the 4 full reads also disagree with each other: bolts with
    a 7.16 mm healed gap, at 4, 5 or 6 solids. Each streamed root record equals one of the full reads.
- **Flagged models below 1 GB.** L1 (275 MB), L2 (263 MB), F1 (84 MB), F2 (94 MB): identical on all 25,923 roots and
  every top-level field. They were compared with a full read on the box and with the grader's stored per-part read-back.
- **Flagged model above 1 GB.** B1 (1.10 GB, 47,970 roots): identical to a full step_check read (2933 s, 16.2 GB RSS).
  The streamed run took 251 s with 8 workers. The largest process peaked at 0.55 GB and the whole tree at 4.2 GB.
- **Sampling (`--max-check`).** m2 and m3 are identical under step_check's sampling. On m1 both runs check the same
  1030 sampled roots; the only differences are the unstable bolt roots.
- **Largest flagged model.** B2 (9.27 GB, 168,834 roots, no full read possible) read completely: 367 chunks, none
  re-cut, no dangling references. It took 1268 s wall with 12 workers (13,014 CPU s). The whole tree peaked at 6.4 GB
  and the largest process at 568 MB.
- **49 more flagged models** (96 to 723 MB, phase 3). Streamed parts are identical to the grader's own stored per-part
  read-back for all 49 models: 1,023,964 of 1,023,964 roots (`equiv/box/equiv_p3.json`). Those stored read-backs come
  from the IFC worker's step_check, which finished its OCC loop and wrote its parts before it was memory-killed.
- **Totals.** 55 flagged models (32.3 GB, 1,266,691 roots) all read completely: no crashed roots, no re-cut chunks.

Cost: about 1.4 to 1.8 CPU s per MB of STEP with 24 MB chunks (2 MB chunks: 2.9, from per-chunk start-up); a full read costs about 1.6 to 2.8 CPU s per MB.
Memory per worker is bounded by the chunk size, not the file size. A full read needs 9 to 16x the file size: 0.95 GB
for 53 MB, 2.1 GB for 142 MB, 4.2 GB for 275 MB, 16.2 GB for 1.1 GB.

## Files

- `step_verify_big.py`: the tool (version 2026-10-02b).
- `to_final_result.py`: builds the final-pass readback record.
- `equiv_compare.py`: pairwise comparison of two runs.
- `box/equiv_summary.py`: equivalence with the kernel's own run-to-run variation measured.
- `integration/`: grader and IFC worker patches, the patched files, and the offline test with its box log.
- `box/`: the BOX-A job runner (`jobq.py`), task generators (`make_tasks.py`, `make_tasks_p4.py`), post-processing
  (`post.py`, `predict_class.py`, `spec_p3.py`) and the SSM launch scripts.
- `final/`: the 28 applicable records plus `models.json`, `predict.json`, `nonpos_where.json`, `runs.json`. Phase-4
  records accumulate in S3 `final/`. `final_stale/` holds the 27 superseded records.
- `integration/build_index_final_pass.patch` for `coord/build_index.py`: the stale-record guard in `apply_final`, and
  `detail_keys` aware of re-run suffixes (`<id>.v6.step` -> `<id>.v6.src_parts.jsonl.gz`).
- `equiv/box/`, `runs/box/`: evidence JSON copied from
  `s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/step-verify-big/`.
- `_prev/`: the 2026-10-01a version from the previous session. `med/`, `big/`, `probe/`, `equiv/` (top level) and
  `runs/` (top level) hold that session's Mac-side work: the single-product non-determinism probe of root 694 (5, 6, 5
  solids over 3 reads).
