# sds2-weights-failures: SDS2 family weight / weight 5% / stage-2 failure / ValueError

Owner request: fix every converter-fixable flaw now, never fabricate geometry, and prove the rest.

All decoding, conversions, OCC read-back and grading simulation ran on BOX-C (i-0d97427e58ca5ef28). Job folders are
fetched with the fleet's own layout rules (`job2/runana2.py`). Results are under
`s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-weights-failures/`:
- `j2/`: this round, on v5.5.3.
- the top level: the first round, on v5.4.

## Bases and deliverables

The task's base is `sds2-step-pipeline-v5.4.zip` (sha256 `bf4a07fc…f906`). The fleet now runs **v5.5.3**
(`converter.json` 19:53, sha256 `706e1289…c0a9`), so the patch is delivered for both. Both apply cleanly to the
pristine zips with `patch -p1`, run from the folder that holds `sds2-step-pipeline/`.

| file (`patch2/`; also in `s3://annotationprod/cad-disk-extract/_control/z3conv/sds2/pfix/sds2-weights-failures/`) | what |
|---|---|
| `sds2-weights-failures-v5.5.3.patch` | converter patch vs v5.5.3 (the fleet's current zip). Tested in round j2 |
| `sds2-weights-failures-v5.4.patch` | the same patch vs v5.4 (the task's base). It also carries the `_absurd` tuple fix, which v5.5.1 already shipped. Smoke-tested on BOX-C (run `s54`): YSIDRO, processing-Ted, TEST1 and SHOAL CREEK come out class 1 A in the manifest, Binney class 2 B, all read-back solids valid |
| `fleet-worker.patch` | `_control/z3conv/sds2/worker.py` (sha `795f3c92…`):<br>- `parse_extra` reads the last read-back block;<br>- `manifest_summary` passes the weight split on (summary fields only) |
| `coord-build_index.patch` | **proposed grading rule** (owner / lead decision), `_control/z3conv/coord/build_index.py` (sha `460d0747…`):<br>- the weight bands look at converter-built solids only;<br>- new stand-in type `unindexed_brep`, mapped to `source_file_missing` |

Overlap with other work:
- The `sparse_layout` stale-record hunk is copied byte for byte from the SDS2 fixer's v5.5.4 draft (`sds2_v5/rel554`).
  If v5.5.4 ships first, `patch` reports that hunk as already applied.
- The piece-table `slot_size_job` draft in `sds2_v5/v5work` is the fixer's. It is not in this patch, but it fixes the
  `test` 8.004 stage-2 failure (section 1e) and should ship.
- Nothing here touches `brep.py` (sds2-approx-pieces-7x) or the grating / cylinder code (sds2-grating-cylinders).

## 0. The four items now (live index 02:51Z) and what this patch does with them

The counts grew since the task was written (58 / 43 / 10 / 15), because the fleet re-ran thousands of SDS2 jobs on
v5.4.1-v5.5.0.

| item | rows now | root causes (proved on the jobs, sections 1-3) | resolution |
|---|---|---|---|
| sds2 stage 2 failure | 68 (class 2, members-only stage 1) | 39 `invalid_solids`, split in two:<br>- 31: the fleet judged the pre-repair read-back block;<br>- 8: the repair pass could not drop parts that failed the assembly check.<br>21 `missing_job_file`: no piece table `subm/subm_idx` in the job folder.<br>6 `steel_weight_mismatch`:<br>- AGRANCLISSEMENT x3: cold-formed studs approximated at 15.9x;<br>- MOUNTAIN VIEW x2: a 14.7x bent-plate fallback;<br>- `test` 8.004: wrong piece-table layout.<br>1 `Bnd_Box is void` (Nantucket).<br>1 v4 `ZeroDivisionError` (Seaport L4) | 66 fixed in the converter. `test` needs the fixer's `slot_size_job` draft. Seaport L4 has a piece-table variant the decoder does not read (not fixed). None of them can honestly reach class 1: every one keeps other class-2 needs (sections 1a-1e) |
| valueerror | 15 (class 3) | 13 BG PODIUM / Boston Garden 7.331 were v4 runs (`PLG12x14x300: built-up dimensions match neither name nor weight`, fixed in v5.0); 15-027 CSU 7.312 (stale member records); 100_Binney_Slab 7.243 (no work-point key) | CSU and Binney fixed (class 3 -> class 2). BG PODIUM: v5.x no longer raises; the run time is dominated by the assembly check (section 2) |
| sds2 family weight | 718 (class 2) | per family (section 3):<br>- 144 rows only in families whose untagged converter geometry was wrong: RB, WS, TWS, THD, HS, BLT, RD;<br>- 269 rows only in families written as SDS2's own exact B-rep, where SDS2's recorded weight follows its own weight conventions;<br>- 120 rows only in tagged stand-in families;<br>- 185 mixed | converter: fixed. SDS2 weight conventions: proved, plus a proposed grading rule. Stand-ins: graded by the stand-in rule (approx-pieces item) |
| sds2 weight 5% | 73 (class 2) | 29 reused v4 results; 44 v5.x rows dominated by exact W / WT / C (fillets drawn from SDS2's k_det, while the recorded weight is catalog lb/ft) and by exact deck | re-run the v4 rows; the rule makes the 5 % band measure converter-built solids only |

Class-1 lifts are few, and honestly so: 5 of these rows reach class 1 (section 5).
- 2 with the converter patch alone (processing-Ted x2);
- 3 more with the proposed rule (YSIDRO, TEST1, SHOAL CREEK).

The other rows keep other class-2 needs: approximate 7.1 pieces, joists, envelopes, nominal bolts. Those belong to
other items.

## 1. Stage-2 failures (68 rows; all are members-only stage-1 fallbacks today)

Per job: `data/item_jobs.json`. The fleet's records and stage-2 logs: `data/stage2_valueerror_fleet_scan.json`.

Tally:

| group | jobs | outcome |
|---|---|---|
| parser fix only, no re-run (1a) | 31 | stage 2 accepted |
| `DROP_LABELS` fix, re-run (1a) | 8 | verified on CCJ, POLICE HEADQUARTERS and BAHAMAR BLDG#40, all accepted. The other 5 (4 CCJ copies + 9NOV_330PM) fail the same way on the same parts (identical counts in the fleet logs) |
| no piece table (1b) | 21 | stage 2 converts. Verified to acceptance on 6: TATTIER, RCMS x2, IMS6, FORD HUB, plus BOSK_E converted; the others follow the IMS6 / FORD HUB path |
| steel mismatch (1c) | 5 of 6 | AGRANCLISSEMENT x3 and MOUNTAIN VIEW x2, verified on one of each. `test` needs the fixer's `slot_size_job` (1e) |
| `Bnd_Box is void` (1d) | 1 | stage 2 accepted |
| Seaport L4 (1e) | 1 | **not fixed**: a piece-table variant the decoder does not read |

That is 66 fixed by this patch, `test` by the fixer's draft, and 1 open.

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

Re-runs on v5.5.3 + patch (BOX-C, full fleet command, graded with the patched parser, the worker's acceptance rule and
the coordinator's `classify_sds2`):

| job | fleet (v5.4.1 / v5.5.0) | v5.5.3 + patch |
|---|---|---|
| CCJ_job 7.132 (2224113a) | stage 2 rejected (42,038 / 41,921 valid -> 111 invalid after both passes); class 2 C | stage 2 **accepted**: 41,927 solids, 41,926 valid; 111 instances of the assembly-check parts dropped and reported; steel 1.019; class 2 B (approx pieces 7.1, joists, 111 pieces not built, 1 invalid) |
| POLICE HEADQUARTERS 7.135 (13e09cfa) | rejected (46 invalid on every pass); 2 C | **accepted**: 25,411 / 25,411 valid; the 46 L5x5x5/16 left out and reported; steel 1.003; 2 B |
| BAHAMAR BLDG#40 7.135 (a298ddfe) | rejected (95 invalid after both passes); 2 C | **accepted**: 37,678 / 37,678 valid; 95 assembly-check instances dropped and reported; steel 1.022; 2 B |
| GREAT OAKS 7.132 (8dbd9387) | rejected on the first block (13,626 / 13,606); 2 C | **accepted**: 13,618 / 13,618 valid after repair pass 1; steel 1.026; 2 B |


### 1b. `missing_job_file` (21): the job folder has no piece table `subm/subm_idx`

Every one of the 21 failed at `open(subm/subm_idx)`. The fleet's file lists (`data/no_table_jobs.json`) show what
the folders hold:
- 16 have no `subm/` piece data at all;
- 2 have only `subm/subm_ctl`;
- 4 still hold the piece files: BOSK_E 8.010 (54,492), TATTIER NEW ALBANY 7.312 (4,439), RCMS 7.039 (2,097) and
  RCMS 7.039 (46).

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

Re-runs on v5.5.3 + patch:

| job | fleet | v5.5.3 + patch |
|---|---|---|
| TATTIER NEW ALBANY 7.312 (86b5ce39), 4,439 piece files | stage 1, members only; 2 C | stage 2 **accepted**: 59,265 / 59,265 valid. 6,592 unindexed pieces (1 not closed), 644 envelopes, 17,343 SDS2 bolts; class 2 B (`source_file_missing: sds2 piece table absent` with the coordinator patch) |
| RCMS 7.039 (1112e842), 2,097 piece files | stage 1; 2 C | **accepted**: 33,831 / 33,831 valid. 5,373 unindexed pieces (69 not closed), 1,379 joist stand-ins, 13 envelopes; 822 t; bbox 173 x 90 x 13 m; 2 C |
| RCMS 7.039 (bee9c6a7), 46 piece files | stage 1; 2 C | **accepted**: 26,003 / 26,003 valid. 336 unindexed pieces, 473 envelopes; 2 C |
| BOSK_E 8.010 (44e6352e), 54,492 piece files | stage 1; 2 C | converted in 2,053 s: 63,705 unindexed pieces (211 not closed), 286 envelopes, 1.9 GB STEP. The read-back was still running after 70 min when this was written; the result lands in `j2/t2w/44e6352e…/` |
| 19002-IMS6 7.720 (fb1cae54), no `subm/` | stage 1; 2 C | **accepted**: 108,894 / 108,894 valid (3,205 envelopes, 128 joist stand-ins, 34,509 SDS2 bolts); class 2 B, only need `source_data_absent: undetailed members` |
| FORD HUB 7.619 (8744c89e), no `subm/` | stage 1; 2 C | **accepted**: 458,759 / 458,759 valid (8,477 envelopes, 150,094 SDS2 bolts); class 2 B, only need `source_data_absent: undetailed members`. 99 min end to end on the loaded box (fleet limit 4 h) |
| Franklin Park 7.516 (59f9c76c), no `subm/` | stage 1; 2 C | stage 2 converts (6,474 envelopes, 1 joist stand-in; earlier round, stopped before the read-back); same path as IMS6 |


### 1c. `steel_weight_mismatch` (6)

- **AGRANCLISSEMENT TRIMAX 7.312 (x3).** 254S89-144M cold-formed studs: the record says 7.53 lb/ft, the closed
  B-rep is 3.71 lb/ft (its own d / bf / lip / t give about 3.8). v5.x rejected the B-rep at the 0.6-1.6 gate and
  wrote a 15.9x profile. `_stock_match` accepts the B-rep (section 3a).
- **MOUNTAIN VIEW BLDG#B-G 7.433 (x2).** 300 x BPL10GAx83 3/16 (SDS2 14.0 lb each) went through the bent-plate
  fallback at 206 lb each (14.7x, +57,600 lb). The fallback gate dropped only pieces > 5x *and* > 1,000 lb over. It
  now also drops pieces >= 10x and > 50 lb over, and those get the piece-table slab stand-in.
- **`test` 8.004.** The piece table is read with the wrong layout (steel 2,198x). This is the fixer's
  `slot_size_job` draft, section 1e.

Re-runs on v5.5.3 + patch:
- **AGRANCLISSEMENT (c55bc33d).** v5.5.3 base: steel 1.652, manifest class 0 (47 of 796 pieces not built). Patched:
  steel 1.020, 2,697 / 2,697 valid, 2 pieces gated; stage 2 **accepted**, class 2 B.
- **MOUNTAIN VIEW (fa837f3e).** v5.5.3 base: steel 1.545, rejected. Patched: 1.007, 5,231 / 5,231 valid, stage 2
  **accepted**, class 2 B. The BPL family flag goes away under the proposed rule.


### 1d. `standard_constructionerror` (Nantucket JOB 29MAY14_MTTL 7.312)

`derive_bolt_holes` asked a part with a void bounding box for its corners, and `Bnd_Box is void` failed the whole
stage 2 (v5.4.1 and v5.5.3 alike). Such parts are now skipped, since they cannot be a bolted ply.

Re-run: v5.5.3 base fails as the fleet did. Patched: stage 2 **accepted**, 131,549 / 131,549 valid, steel 1.081,
class 2 B (approx pieces 7.3, concrete, ...).


### 1e. `zerodivisionerror` (Seaport L4 7.619) and the piece-table layout

- **Seaport L4 7.619.** The fleet's record is a v4 run (`plate_outline` / 0, guarded since v5.0). On v5.4 + patch
  and on v5.5.3 + patch + `slot_size_job`, stage 2 runs but is broken: steel 0.66x, 3,451 of 7,192 pieces with names
  like `@`, `?`, `TD-`.
  - Its `subm_idx` (130.9 MB, 81,858 piece files) holds piece names at irregular spacings (764 / 382 / 504 / 642 B).
  - No fixed slot fits: at 1,024 B only 1,560 of 81,858 piece slots hold a name.
  - This is a piece-table variant the decoder does not read: not fixed here (decoder layout item).
- **`test` 8.004 with the fixer's `slot_size_job`** (v5.4 + this patch + `v5work/decode/piece_table.py`, run `rp9t`): steel
  2,198x -> 1.023 (2,734 t vs SDS2 2,671.5 t), 84,177 placed solids with 3 invalid before the repair pass, which is within
  the fleet limit of 84. Manifest class 2 B (2,165 profile extrusions, 36 joists). Fleet v5.1: members only.

## 2. ValueErrors (15 rows, class 3 `failed`)

| jobs | fleet record | root cause | after |
|---|---|---|---|
| 15-027 CSU 7.312 (347cb74f) | v5.4.1 `mem_idx: member work points not found` | 810 of 10,452 structural records have NaN end points. `sparse_layout` rejected the whole validated 2,944-B layout on the first one, and `calibrate()` found no work-point key either | patched v5.5.3: stage 2 accepted, 14,438 / 14,438 valid, steel 1.030, **class 2 C** (needs: approx pieces 7.3, 72 pieces gated as > 5x fallbacks, 1 built-up estimate, 3 envelopes). The hunk is the fixer's v5.5.4 draft code, byte for byte |
| 100_Binney_Slab_Job 7.243 (a47a1307) | v5.5.0 same message | three MISC members, two of them with zero work points: no key match for `calibrate()`, and `sparse_layout` knew 2,494-B slots only for 7.245 | the module's own documented 7.243 layout (validated on 50_Binney against its IFC) is now a sparse fallback. The job holds one concrete slab: 1 solid, **class 2 C** (`source_data_absent: concrete shapes`) |
| BG PODIUM x12, Boston Garden Checkers x1 (7.331) | **v4** runs: `PLG12x14x300: built-up dimensions match neither name nor weight` | v4's built-up profile check; fixed in v5.0 (all 13 have a complete piece table) | re-run on v5.x. BG_PODIUM_Job 436d09 on v5.4 sat in `assembly_check` for > 2 h 20 min at 52 GB RSS (py-spy: `assembly_check <- convert`); the temporary assembly STEP had 67.7 M entities. v5.5.3 + patch with `SDS2_ASSEMBLY_CHECK_MAX=0`: 1 h 26 min to build the pieces, then the STEP write, with the read-back still to come (run `bgw`). So: no more ValueError, but a run-time risk against the fleet's 4 h limit. `ASSEMBLY_CHECK_MAX` counts parts, not faces; a face-count cap is a follow-up for the SDS2 fixer (no geometry change) |

## 3. Weights, per family: converter geometry wrong (fixed) vs SDS2's recorded weight (proved) vs stand-ins

Method. `wdump.py` runs the pipeline's own `to_step2.convert` with the STEP write stubbed. For every piece it dumps:
- SDS2's piece weight and the written solid's weight;
- the builder and the piece-table fields;
- the section record (catalog lb/ft, d, bf, tf, tw, k);
- the piece's own B-rep volume, with and without its decoded holes;
- the stud / rod ring geometry.

Coverage:
- round 1 (v5.4): 51 representative jobs and the 41 v4-reused weight-5% jobs;
- round j2 (v5.5.3): the families new since then (HS, RPL, FL, L, MA, SH, DK, HSS) on 11 jobs.

The family rows of the live index, split by how each flagged family is written:

| geometry of the flagged families in a row | rows | what moves the weight |
|---|---|---|
| exact only (SDS2's own piece B-rep) | 269 | SDS2's weight conventions (3b) |
| built only (untagged converter primitives) | 144 | converter geometry (3a, fixed) |
| tagged stand-ins only | 120 | the stand-in itself (3c) |
| mixed | 185 | the same causes, combined |

### 3a. Converter geometry wrong: fixed in the patch

| family (rows) | what v5.4-v5.5.3 wrote | proof (SDS2's own data) | after the patch |
|---|---|---|---|
| RB round bars (194 built + 49 tagged) | 7.5+ straight-rod guess sized from table `W`, which there is 0.25, not the diameter. Bent / curved bars: only the first ring pair, or a straight bar | STERLING VIII RB3/4 x 648 in: closed B-rep 80.668 lb vs SDS2 80.658 | v5.5.3 -> patched (family ratio):<br>- STERLING VIII 0.1118 -> 1.0001 (the 101 tagged mesh cylinders are now exact B-reps);<br>- THERMOFISHER 0.5146 -> 1.0029;<br>- Cats Rail 0.7817 -> 1.0047;<br>- ASC 0.1885 -> 1.0008;<br>- RCMS 7.039 0.9248 -> 0.9951 |
| WS weld studs (94) | head only: station 3.6875 / radius 0.4375 split by 3-decimal rounding, so the shank ring was lost | P545 WS1/2: true cylinders 0.2750 vs SDS2 0.2749 once the rings merge | P545 0.8568 -> 1.0001 (v5.5.3; the same 14,719 pieces, 920 fewer read-back leaves: split stud segments merged). EDWARDS AFB 0.146 -> 1.0001 (v5.4 round) |
| HS headed studs (37: 32 copies of RCMS 7.039, Henderson Hospital 7.618/7.619, 7.135) | RCMS 3.47x on 400 pieces, Henderson 4.47x: wrong rings / straight rods | the stud's own closed B-rep matches SDS2 | RCMS 7.039: 3.4692 -> 0.9948 (v5.5.3, 400 studs). Henderson 7.618: HS no longer off (built part 1.0066). 8.007 23-06 PH: exact HS B-reps 0.964 = the 16-gon convention (3b) |
| TWS / THD threaded studs (37 / 13) | straight rod with L = table L (holds the diameter on stud records) and d = W | CENTER GROVE THD STUD 3/4: face-vertex extent 2.0 x 0.75 in gives 0.2506 lb = SDS2; SHERIFFS TWS2: 2.5 x 2.0 in gives 2.227 = SDS2 | v5.5.3 -> patched: CENTER GROVE THD 0.0651 -> 1.0001; SHERIFFS TWS 0.0195 -> 1.0001. Both are still tagged `[approx: straight rod ...]` (no closed B-rep), now with the right size |
| BLT SDS2 bolt pieces (20) | shank lost (0.3125 split); hex head as a cylinder through its corners (+21 %) | ASC 1/2 x 3 1/2: SDS2 0.245 lb; hex prism of the stored 6 vertices + shank 0.2535 | ASC 1.0845 -> 1.0356 (v5.5.3) |
| MA (Queen Street 7.708, 4 rows) | 3.47x | same mechanism | no longer off |
| exact pieces rejected by the 0.6-1.6 weight gate: PL, L, ROUND, W, cold-formed `?` | approximation (profile / plate fallback) because SDS2's recorded weight disagrees with SDS2's own stock | EDWARDS AFB PL3/8x3 5/16: L x W x T 7.93 lb, B-rep 7.83, recorded 4.69. processing-Ted L8x8x3/4: catalog 1,556 lb, B-rep 1,563, recorded 4,000. YSIDRO W360x237/x382/x463: `job_mtrl` gives all three 335.3 lb/ft (placeholder); the B-reps are 163 / 261 / 315 lb/ft. AGRANCLISSEMENT 254S89-144M (16 ga stud): record 7.53 lb/ft, B-rep 3.71 lb/ft | exact B-rep when it equals SDS2's own stock; listed in `weight_check.sds2_weight_outliers` and kept out of the ratio. v5.5.3 runs:<br>- processing-Ted 0.793 -> 1.011 (class 2 -> 1);<br>- AGRANCLISSEMENT 1.652 -> 1.020;<br>- YSIDRO 0.840 -> 0.923 (the rest is the W360 placeholder lb/ft) |

### 3b. SDS2's recorded weight is a table / convention; the solid is SDS2's exact B-rep (no converter fix; grading rule)

| family (rows exact-only) | solid / SDS2 | proof |
|---|---|---|
| W, WT, C, MC, S, H (73 / 33 / 36 / 2 / -, 4) | +2.5 ... +8 % (lighter sections higher) | SDS2's B-rep section carries fillets of radius k - tf from the section's own `k` field (k_det), while the recorded weight is catalog lb/ft x L.<br>- W10x12 (TEST1): catalog 12 lb/ft x L = SDS2 3,393.9 lb exactly; B-rep 3,592.5 (+5.85 %); plates 3.459 in² + 4(1 - π/4)(0.75 - 0.21)² = 3.709 in².<br>- RCMS C3x6: catalog 65.72 = SDS2, B-rep 69.88 |
| CK / DK steel deck (75 / 16) | +11.2 ... +11.8 % (1 1/2 in deck), +27.7 % (1 in) | every deck piece in 6 jobs: SDS2 weight = 0.100 in (void: 0.1345 in) x the B-rep's developed area x 0.2836 lb/in³, to 4 digits. 19156_610 DK1 1/2x36: 152.37 vs B-rep 170.13 |
| PL / FL / RPL / L with decoded holes (14 / 70 / 32 / 33) | 0.80 ... 0.95 | the recorded weight is the gross stock, the B-rep has SDS2's own decoded holes / slots cut:<br>- RCMS RPL1x2: B-rep 0.7363 = SDS2 0.7362; with its 13/16 hole 0.5893 (0.807).<br>- RCMS FL1/2x4 1/2: L x W x T 6.062 = SDS2 6.0616 = B-rep; 3 holes -> 5.0915.<br>- THIRD DISTRICT L4x3x5/16 x 17.5: catalog 10.5 = SDS2; B-rep 10.595, 6 holes -> 9.887 (0.94).<br>- bernardPSC FL3/8x4: SDS2 3.614 removes less than the stored 13/16 x 1 13/16 slots (B-rep 3.829 -> 3.404) |
| CP / CHKD checkered plate (19 / 16) | 3/8: 0.936; 1/4: 0.907; 1/8: 0.829 | SDS2 weight = area x AISC floor-plate weight (1/8 6.16, 1/4 11.26, 3/8 16.37 psf). SOCORRO CHKD1/4: 6.595 ft² x 11.26 = 74.27 lb = SDS2; the B-rep is the flat plate (no lugs in the data) |
| ROUND / HSS exact (68 / 30) | 0.93 | B-rep wall = design thickness (0.93 x nominal), recorded weight on nominal (Cutler Ice Shield, 1,981 pieces; RCMS ROUND 0.9347) |
| SD (dome) (4) | 0.6667 exactly | SDS2 weighs it as the bounding cylinder; the B-rep is the dome (2/3) |
| HD / HSA / WS / HS exact stud B-reps | 0.96 | 16-gon faceted solid vs SDS2's true-cylinder weight |

### 3c. Tagged stand-ins (already graded as stand-ins: item "sds2 approx pieces", not this patch)

- CV clevis (75), TB turnbuckle (40), ADJ / BPL bent plates, HSS / W / ROUND `profile_fallback` on open B-reps.
  Examples: Henderson W 1.94x, HSS 1.80x; NWCC HSS 3.15x; 19156_610 BPL 8.0x.
- One case was gross enough to stop stage 2 and is gated here (section 1c): MOUNTAIN VIEW, 300 x BPL10GAx83 3/16 at
  14.7x. The 5-10x fallbacks (19156_610 BPL 8.0x) remain for that item.

## 4. Proposed grading rule (owner / lead decision: `coord-build_index.patch`)

The patched converter splits the weight tally by geometry source:
- `weight_check.by_source.{exact, built, standin}`, with the same three parts in every `by_family` entry;
- `exact`: SDS2's own piece B-rep;
- `built`: solids the converter constructs and writes untagged (stud / rod / bolt cylinders, hex prisms);
- `standin`: tagged `[approx: ...]` solids.

The weight check exists to catch converter geometry that is wrong *without* a tag. Section 3b shows that exact
B-reps differ from SDS2's recorded weight only through SDS2's own tables and conventions:
- k_det fillets;
- deck at 0.100 in;
- floor-plate psf;
- gross stock with holes and slots ignored;
- design wall thickness;
- domes weighed as cylinders.

Tagged stand-ins are already graded by the stand-in rule. The proposal:
1. **Class-1 5 % band** on `(exact_sds2 + standin_sds2 + built_step) / total_sds2`. Only untagged converter-built
   solids move it. The 0.75-1.3 "broken" band stays on the overall ratio, to catch gross decoding errors.
2. **Family 5 % rule** (n >= 5) on the `built` part of each family.
3. **Info only**, no class effect:
   - exact families outside 0.85-1.2 ("SDS/2 recorded weight differs from its own piece B-rep ... SDS/2 weight
     tables / conventions, not converter geometry");
   - the `sds2_weight_outliers` count.
4. Manifests without the split (v5.5.3 and older) keep today's rule.

`RULES` keys: `sds2_weight_converter_built_only` (default true) and `sds2_exact_family_band` ([0.85, 1.2]).

The same patch maps the new stand-in type `unindexed_brep` to `source_file_missing | sds2 piece table absent`.
Without that mapping it would fall to the generic `converter_feature` key.

`fleet-worker.patch` does two things:
- passes the split and the outlier count through `manifest_summary`;
- makes `parse_extra` read the last read-back block (the acceptance counts come from the converter's
  `run_batch.parse_log`, fixed in the converter patch).

## 5. Class-1 lifts: what is real

A row lifts to class 1 only when nothing else blocks it: no stand-ins (source-data-absent ones included), no skipped
pieces, no other issue. In the live index, the rows whose only converter needs are the weight items, or a
weight-gate rejection behind `approx pieces 7.x`, are these. All were re-run on BOX-C and graded with the
coordinator's own `classify_sds2` (current and patched `build_index.py`):

| job | live | v5.5.3 + patch, current rule | + proposed rule |
|---|---|---|---|
| processing-Ted 7.115 (1b5682da, 72f05999) | 2 B: steel 0.793, L family, L8x8x3/4 approximated (B-rep rejected at the gate) | **1**: the exact L8x8x3/4 B-rep is written (catalog 1,556 lb, B-rep 1,563, recorded 4,000: an outlier); steel 1.011 | 1 |
| YSIDRO 7.135 (1b39fd69) | 2 B: steel 0.840, W family, W360x237 approximated | 2: steel 0.923, W 0.917 (`job_mtrl` W360 lb/ft placeholders; exact B-reps) | **1** |
| TEST1 7.331 (799ba840) | 2 C: steel 1.0585 (one exact W10x12) | 2 C | **1** (k_det fillets, section 3b) |
| SHOAL CREEK BLDG-B 7.135 (c46e0c62) | 2 C: L family 0.926 (exact angles with decoded holes) | 2 C | **1** |
| chandu_job 7.323 (ab3b8a66) | 2 B: steel 1.054 (a v4 result) | 2 B: v5.4+ adds bolt-derived / mating-hole stand-ins | 2 B (not a lift) |

(The corpus letter is left out because the simulation has no worker piece inventory, which decides A vs C.)

So: 2 lifts from the converter alone and 3 more if the owner adopts the rule, 5 in all. Every other row of the four
items keeps another class-2 need.

## 6. Regression: the fixer's control jobs (v5.5.3 vs v5.5.3 + this patch)

Inputs: the five control jobs the SDS2 fixer uses (`/work/agentwork/sds2v54/jobs`, used read-only). The baseline is
the fixer's own v553b run (`sds2v54/f553/v553b`). Command: `sds2_to_step.py --stage 2 --verify`.

| control | class | read-back solids (valid) | steel ratio | what changed |
|---|---|---|---|---|
| AGNEWS-R | 2 B -> 2 B | 1,546 (1,546) -> same | 0.9969 -> 0.9969 | nothing (identical counts and stand-ins) |
| GMS | 2 B -> 2 B | 9,171 (9,171) -> same | 1.021 -> 1.021 | nothing |
| AGNEWS-T | 2 B -> 2 B | 5,786 (5,786) -> same | 1.0233 -> 1.0232 | 116 `mesh_cylinder` stand-ins -> the pieces' own closed B-rep: 3 guessed straight rods (pieces exact 1,406 -> 1,522) |
| METHODIST | 2 B -> 2 B | 12,386 (12,386) -> same | 1.007 -> 1.007 | 58 `mesh_cylinder` -> exact B-rep: 10 pieces (4 guessed rods, 6 off-weight rings). Parts written flat after the assembly check: 2 -> 12 |
| TYSONS | 2 B -> 2 B | 6,885 (6,885) -> 6,901 (6,901) | 1.007 -> 1.007 | 146 `mesh_cylinder` -> exact B-rep: 13 guessed rods. The 16 extra read-back solids are multi-lump exact B-reps |

No control lost a solid, a valid solid or a piece. Weight split on the controls:
- `built` (untagged converter primitives): 1.0001-1.0076;
- `exact` (SDS2's B-rep): 0.9965-1.0233.

### 6b. Weight regression: v5.5.3 vs v5.5.3 + patch on the same box

Each cell: read-back solids (valid); steel ratio; class and family flags under the coordinator's current rule. The
last column is the patched run graded with the proposed rule. Source: `data/regrade_j2.json`.

| job | v5.5.3 | v5.5.3 + patch | + proposed rule |
|---|---|---|---|
| STERLING VIII 7.613 | 28,841 (28,841); 1.018; class 2; RB | 28,841 (28,841); 1.0222; class 2; - | class 2; - |
| P545 HANGAR 7.135 | 51,803 (51,803); 1.0009; class 2; WS | 50,883 (50,883); 1.0009; class 2; - | class 2; - |
| CENTER GROVE 7.708 | 11,417 (11,417); 1.0048; class 2; THD | 11,417 (11,417); 1.0048; class 2; - | class 2; - |
| SHERIFFS OFFICE 7.425 | 15,308 (15,308); 1.0178; class 2; WT, TWS | 15,308 (15,308); 1.0179; class 2; WT | class 2; - |
| 17391 ASC 7.613 | 6,438 (6,438); 1.0163; class 2; RB, BLT | 6,438 (6,438); 1.0166; class 2; - | class 2; - |
| processing-Ted 7.115 | 9 (9); 0.793; class 2; L | 9 (9); 1.0108; **class 1**; - | class 1; - |
| YSIDRO 7.135 | 191 (191); 0.8397; class 2; W | 191 (191); 0.9229; class 2; W | **class 1**; - |
| RCMS 7.039 | 38,994 (38,994); 1.0181; class 2; ROUND, HS, C, RB, RPL | 38,946 (38,946); 1.0122; class 2; ROUND, C, RPL | class 2; - |
| Queen Street 7.708 | 17,671 (17,659); 1.0176; class 2; RB, WS | 17,679 (17,679); 1.0191; class 2; - | class 2; - |
| Cats Rail 7.312 | 43,244 (43,244); 1.0582; class 2; W, RB | 43,258 (43,258); 1.0583; class 2; W | class 2; - |
| THERMOFISHER 7.708 | 34,277 (34,277); 1.0082; class 2; RB | 34,303 (34,303); 1.0097; class 2; - | class 2; - |
| 16-4742 Eastwood 7.312 | 34,147 (34,146); 1.0156; class 2; RB, ROUND, H | 34,139 (34,138); 1.016; class 2; ROUND, H | class 2; - |
| Cardinal Misc 7.135 | v5.4: still in the bent-plate search after 45 min | 1,133 (1,133); 1.0255; class 2; ROUND | class 2; - |

No piece was lost:
- `placed_pieces`, `pieces_written` and `solids_written` are identical in every pair;
- exact pieces went up: THERMOFISHER +1,860, RCMS +275, Cats Rail +86, Queen Street +27, Eastwood +22.

Lower read-back leaf counts (P545 -920, RCMS -48, Eastwood -8) are studs whose split ring segments merged into one
shank. Queen Street shows the `DROP_LABELS` fix:
- v5.5.3 listed 12 instances as dropped (`exact_solid_invalid_at_placement`), yet still wrote them, 12 invalid;
- the patch really leaves them out: 17,679 of 17,679 valid.

## 7. What is not fixed here, and why

- **Piece-table layout, `test` 8.004** (steel 2,198x): the SDS2 fixer's `slot_size_job` draft
  (`v5work/decode/piece_table.py`) fixes it (section 1e). It is the fixer's code, so it is not duplicated here.
- **Piece-table variant, Seaport L4 7.619** (names `@`, `?`, `TD-`; steel 0.66x): `slot_size_job` does not fix it. Its
  `subm_idx` has no fixed slot. This needs decoder work on that table variant (1 job).
- **5-10x bent-plate / profile fallbacks**: tagged stand-ins, item sds2-approx-pieces-7x. Only the >= 10x / +50 lb
  cases are gated here, because one of them stopped stage 2.
- **Exact solids still invalid after STEP read-back** (POLICE HEADQUARTERS L5x5x5/16: one face of 60 invalid after the
  round trip, and ShapeFix does not repair it): left out and reported as `exact_solid_invalid_at_placement`. A B-rep
  repair (sds2-approx-pieces-7x `brep.py` work) may recover them.
- **Jobs whose folder has no `subm/` at all** (16 of the 21 no-piece-table jobs): members only is all the source
  holds. The job folders are as extracted from their archives (file lists checked in `data/no_table_jobs.json`).
- **SDS2's recorded weight conventions** (section 3b) are source facts, not converter errors: grading rule proposal.

## 8. Files

Still running on BOX-C when this was written:
- BOSK_E (`j2/t2w`) and BG PODIUM (`j2/bgw`);
- both end by 06:30Z at the latest (`timeout 10800`) and upload to `j2/<tag>/`.

Everything else of this slug on the box is stopped. STEP outputs and job copies are deleted; 8 GB remains, the env
and the two running jobs.


- `patch2/`: the deliverables (table at the top).
- `work553/sds2-step-pipeline`, `work54b/sds2-step-pipeline`: patched trees.
- `job2/`: every script that ran on BOX-C in round j2:
  - `runana2.py`: fetch + run, the fleet's layout rules;
  - `gradecheck2.py`: worker acceptance + coordinator grading, current and patched;
  - `promote_check.py`: re-judges the fleet's own stage-2 outputs;
  - `s2scan.py`, `ntscan.py`: fleet records and file lists;
  - `probe_*.py`;
  - `run_*.sh`.
- `job/`, `ana/`: round 1 (v5.4) scripts and per-piece dumps.
- `ana2/`: round-j2 per-piece dumps (`nf553/`), grading output (`gc.json`, `pc39.json`), control manifests (`ctl/`
  vs `f553/`).
- `data/`: `item_jobs.json` (all 83 stage-2 / ValueError ids with the fix that applies), `no_table_jobs.json`,
  `stage2_valueerror_fleet_scan.json`, `invalid_solids_rejudged.json`.
