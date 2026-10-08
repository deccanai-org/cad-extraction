## 1. Stage-2 failures (68 rows; all are members-only stage-1 fallbacks today)

Per job: `data/item_jobs.json`. The fleet's records and stage-2 logs: `data/stage2_valueerror_fleet_scan.json`.

### 1a. `invalid_solids` (39): the read-back repair worked, the fleet read the wrong block

The worker accepts stage 2 when the STEP read-back has at most max(5, 0.1 %) invalid solids. It takes those counts
from `batch/run_batch.parse_log`, which uses `re.search`, so it read the first read-back block. With `--verify`,
`sds2_to_step.py` repairs invalid solids:
1. pass 1 writes them as placed copies;
2. pass 2 leaves out any that are still invalid;
3. it re-verifies after each pass.

The STEP on disk is the last pass. Example, GREAT OAKS 7.132 (v5.5.0): first block 13,606 of 13,626 valid; after
repair pass 1, 13,626 of 13,626. The worker still saw 20 invalid and fell back to members only.

Fix 1: `parse_log` takes the last match (converter `batch/run_batch.py`; the worker loads it from the zip).

Re-judging the fleet's own `_not_accepted` stage-2 outputs with the patched parser (no re-conversion;
`data/invalid_solids_rejudged.json`):

| jobs | before | after (patched parser + coordinator's `classify_sds2`) |
|---|---|---|
| 31: GREAT OAKS x8, BAHAMAR BLDG#41-50 x8, MARIONCOUNTY x3, BAHA_HOT x5, BAHA_POD x2, Spectrum 2, Misc_1144, PSU MUSIC HALL, Stair-Seacoast, old | stage 2 rejected, class 2 C (members only), need `sds2 stage 2 failure` | stage 2 accepted (0-7 invalid of 6,181-37,538). Class 2 B (30) / 2 C (1), with the job's real needs (`approx pieces 7.1`, joists, ...) |
| 8: CCJ x5, 9NOV_330PM, POLICE HEADQUARTERS, BAHAMAR BLDG#40 | rejected | still above the limit with the parser fix alone: fix 2 |

These 31 do not need a re-conversion: their `_not_accepted/<id>/<label>/` stage-2 STEP is already the repaired one.
The lead can promote them, or simply re-run them on the patched converter.

Fix 2 (the 8): `assembly_check` flags parts that read back invalid through an assembly location. Their instances
were written as placed copies *before* `DROP_LABELS` was looked at. Repair pass 2 could therefore never leave out an
instance that is invalid as a placed copy too, and the same solids came back on every pass:
- CCJ: 117 -> 112 -> 111 invalid;
- POLICE HEADQUARTERS: 46, 46, 46. All 46 are one exact L5x5x5/16, piece 4: one face of 60 is invalid after the STEP
  round trip, and ShapeFix does not repair it (`probe_inv.py`).

The patch makes those instances, and flat-mode exact parts, honour `DROP_LABELS`. They are reported as skipped
(`exact_solid_invalid_at_placement`) instead of being written invalid.

STAGE2_1A_AFTER

### 1b. `missing_job_file` (21): the job folder has no piece table `subm/subm_idx`

Every one of the 21 failed at `open(subm/subm_idx)`. The fleet's file lists (`data/no_table_jobs.json`) show what
the folders hold:
- 16 have no `subm/` piece data at all;
- 2 have only `subm/subm_ctl`;
- 4 still hold the piece files: BOSK_E 8.010 (54,492), TATTIER NEW ALBANY 7.312 (4,439), RCMS 7.039 (2,097) and
  RCMS 7.039 (83).

Piece names, sections and weights live only in `subm_idx`. Placements (member-file blocks) and geometry (piece files)
do not need it.

The patch:
1. Stage 2 runs without the table. `instances._is_71` / `_is_70` take the layout from `main/jsetup` instead of the
   `subm_idx` slot size.
2. Every member gets its SDS2 bolt records, a joist stand-in, or a tagged work-line envelope ("the job folder has no
   piece table ...").
3. Where piece files exist, each piece a member file places is written from SDS2's stored B-rep (`brep_unindexed`):
   - closed, valid solids only; open meshes are left out and counted;
   - decoded holes are cut;
   - tagged `[unindexed: ...]`, stand-in type `unindexed_brep`;
   - the geometry is exact, but nothing can be checked against a name or a weight, so it is never class 1.

Manifest: `counts.piece_table_absent`, `counts.subm_piece_files`.

STAGE2_1B_AFTER

### 1c. `steel_weight_mismatch` (6)

- **AGRANCLISSEMENT TRIMAX 7.312 (x3).** 254S89-144M cold-formed studs: the record says 7.53 lb/ft, the closed
  B-rep is 3.71 lb/ft (its own d / bf / lip / t give about 3.8). v5.x rejected the B-rep at the 0.6-1.6 gate and
  wrote a 15.9x profile. `_stock_match` accepts the B-rep (section 3a).
- **MOUNTAIN VIEW BLDG#B-G 7.433 (x2).** 300 x BPL10GAx83 3/16 (SDS2 14.0 lb each) went through the bent-plate
  fallback at 206 lb each (14.7x, +57,600 lb). The fallback gate dropped only pieces > 5x *and* > 1,000 lb over. It
  now also drops pieces >= 10x and > 50 lb over, and those get the piece-table slab stand-in.
- **`test` 8.004.** The piece table is read with the wrong layout (steel 2,198x). This is the fixer's
  `slot_size_job` draft, section 1e.

STAGE2_1C_AFTER

### 1d. `standard_constructionerror` (Nantucket JOB 29MAY14_MTTL 7.312)

`derive_bolt_holes` asked a part with a void bounding box for its corners, and `Bnd_Box is void` failed the whole
stage 2 (v5.4.1 and v5.5.3 alike). Such parts are now skipped, since they cannot be a bolted ply.

STAGE2_1D_AFTER

### 1e. `zerodivisionerror` (Seaport L4 7.619) and the piece-table layout

- **Seaport L4 7.619.** The fleet's record is a v4 run (`plate_outline` / 0, guarded since v5.0). On v5.4 + patch
  and on v5.5.3 + patch + `slot_size_job`, stage 2 runs but is broken: steel 0.66x, 3,451 of 7,192 pieces with names
  like `@`, `?`, `TD-`.
  - Its `subm_idx` (130.9 MB, 81,858 piece files) holds piece names at irregular spacings (764 / 382 / 504 / 642 B).
  - No fixed slot fits: at 1,024 B only 1,560 of 81,858 piece slots hold a name.
  - This is a piece-table variant the decoder does not read: not fixed here (decoder layout item).
- **`test` 8.004 with the fixer's `slot_size_job`.** STEP_TEST_AFTER
