# sds2-pieces-not-built: SDS2 converter patch

**Base.** The task named v5.4. Since then the SDS2 fixer has published **v5.5.3**
(`sds2-step-pipeline-v5.5.3.zip`, sha256 `706e1289…c0a9`, released 02:11Z). v5.5.3 already contains two fixes that
came out of this item: the "absurd extent" tuple bug, and reference meshes written as face sets. So the primary patch
is rebased on v5.5.3, and a v5.4 port is included as well.

- **How to apply:** `patch -p1 < sds2-pieces-not-built.diff` inside `sds2-step-pipeline/`.
- **Files touched:** `decode/brep.py` and `decode/to_step2.py` only.
- **Interface:** same CLI and same outputs.
- **New manifest keys:** `skipped.needed`, `skipped.source_absent`, `skipped.source_detail`,
  `counts.pieces_exact_without_table_data` and `counts.rolled_sds2_weight_outliers`.
- **Compute:** everything ran on BOX-C (i-0d97427e58ca5ef28).
  - Results: `s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-pieces-not-built/`
    (`ab553/`, `projection/`, `groups2/`, `diag3/`).
  - The earlier v5.4 runs are under `ab/`, `diag*/` and `groups/`.

| file | what |
|---|---|
| `sds2-pieces-not-built.diff` | **the patch**, unified diff vs **v5.5.3**. Checked: applies cleanly and reproduces the tested tree byte for byte. |
| `sds2-pieces-not-built.v5.4.diff` | the same change vs v5.4. It also carries the 5.5.1 shared-tuple `_absurd()` fix that v5.4 lacks. |
| `sds2-slot-size-job.optional.diff` | the SDS2 fixer's `slot_size_job` draft (`v5work/decode/piece_table.py`), unchanged. It applies to v5.4 and v5.5.3 alike. Not part of the patch (§6). |
| `grader/optional_grader_build_index.diff` | optional change to `coord/build_index.py`: skip reasons `source_*` count as `source_data_absent \| sds2 piece geometry absent` instead of `converter_feature \| sds2 pieces not built`. Checked: applies cleanly to the current `build_index.py` (sha256 `e3dc3595…`, 23:26 local). |
| `data/ab553/` | A/B manifests, logs and skip lists: v5.5.3 vs v5.5.3 + patch on 33 jobs. Also `compare553.json` and `table.md`. |
| `data/projection/` | replay of every skipped piece of all 565 live models, v5.5.3 vs + patch: `agg_all.json`, `per_model.json` |
| `data/groups2/`, `data/diag3/` | live skip-reason grouping (565 models); per-piece diagnostics of representative jobs |
| `data/ab/`, `data/groups/`, `data/diag*/` | the earlier v5.4 runs, from the first revision of this patch |
| `job/`, `job/stage2/` | every script that ran on the boxes (`stage2/` = this revision) |

## 1. What "sds2 pieces not built" is made of

Live grading (`class2_fix_plan.json`, 2026-10-02T02:51Z):

- **565 models** (562 class 2, 3 class 3). The task's 264 / 53 is an earlier snapshot: the count grew as the fleet
  graded its v5.4.1 / v5.5.0 results.
- **57** are "lift to class 1 if only fix": 56 imported reference models converted by v5.1, plus jfkf (v5.4.1).
- **By converter label:**
  - v4: 171. These are disk-2 run-2 reuses; `converter.json` has `redo_labels: ["v4"]`, so the fleet is redoing them.
  - v5.4.1: 129. v5.5.0: 102. v5.1: 99. v5.3: 36. v5.4: 22. v5.2: 5. v5: 1.

The table groups the skipped placements of the 394 v5.x models from their own `_skipped.csv` (`data/groups2/`).

| skip reason | v5.x models | placements | root cause | outcome |
|---|---:|---:|---|---|
| `absurd_extent_corrupt_source_geometry` | 114 | 16,977 | converter bug: the shared-part tuple was passed to `_absurd()` | **fixed in v5.5.3 (5.5.1)**. Re-run only. |
| `reference_part_no_closed_brep` | 69 (57 lift) | 3,676,633 | §2.1-2.3 | v5.5.3 writes the sewn-shell failures as face sets. **This patch** closes the meshes that close, writes single triangles, and tags parts with no faces. |
| `reference_time_budget_exceeded` | 7 (5 lift) | 186,329 | 0.26 s per double-sided open part against a 5,400 s budget | **partly**: this patch writes 23 % more parts in the same budget (§2.3). The rest needs `SDS2_REF_BUDGET_S` raised (fleet setting). |
| `no_usable_special_geometry` | 145 | 7,854 | mixed (§2.5, §2.7) | built where the job has the geometry, else a precise `source_*` reason. Gratings are left to `sds2-grating-cylinders`. |
| `fallback_over_5x_source_weight` | 121 | 1,631 | gratings (61 models); rolled pieces whose SDS2 weight is the outlier; hollow pieces built filled | **this patch** for rolled pieces (§2.6) and hollow pieces (§2.4). Gratings: other item. |
| `fallback_builder_failed` | 11 | 35 | zero-length pieces in the source | `source_piece_zero_size` |
| `exact_solid_invalid_at_placement` | 10 | 16 | read-back invalid at placement | not this item |
| `joist_without_depth` | 3 | 3 | `26 OWSJ` (Canadian series) unknown to `joist.DESIG` | not changed (the fixer's joist module) |

The v4 rows (171 models) carry the same three steel reasons: `no_usable_special_geometry` 29,621 placements,
`fallback_builder_failed` 2,622 and `fallback_over_5x_source_weight` 1,620. Their skip lists are v4 decisions, and a
v5.5.x re-run replaces them.

## 2. Root causes and fixes in this patch

### 2.1 Reference meshes that close once SDS2's own degenerate faces are dropped

`brep.clean_faces()` and `_solid_cleaned()` form the last pass of `brep.solid()`. They target two kinds of mesh:

- **Topologically closed meshes with zero-area triangles.** These are collinear triples in cap triangulations, e.g.
  data-3 jfkf / vfgrt 7.331: 47 extruded beams with 4 such triangles each. OCC accepts the degenerate face, but sewing
  then leaves 2-6 free edges. v5.5.3 therefore writes the part as an unsewn face set.
- **Double-sided meshes.** Every face is stored twice, so every edge has 4 users.

The repair:

- It drops the zero-area faces and keeps one copy of each repeated face.
- It splits the T-junctions this leaves, using the existing `conform()`.
- It accepts the result only as a closed solid with volume. No face is ever added.
- `brep.shell()` skips zero-area faces too, so an open part is written as a valid sewn shell instead of a face set.

Effect:

- **jfkf and vfgrt: class 2 R → class 1 R.** All 694 placements are closed solids that read back valid. v5.5.3 alone
  gives 624 open face sets.
- KL: 47 more closed solids.
- The pass runs in `brep.solid()`, so it also reaches **steel pieces** whose B-rep failed only because of degenerate
  faces:
  - RCMS 7.039: 19 HSS / PL pieces.
  - 061219_Temp 7.613: 22 HSS3x3x5/16.
  - These pieces are now exact SDS2 B-reps instead of tagged profile extrusions. They pass the existing 0.6-1.6 weight
    check, and every read-back is valid.

### 2.2 Single-triangle reference parts

These piece files hold 3 vertices and 2 faces: one triangle stored on both sides.

- `brep.parse()` required at least 4 vertices, so even v5.5.3 drops them. Data-3 hjj alone has 1,179 such files
  and 86,230 placements.
- `parse(..., nvmin=3)` is used only by `brep_reference()`. Such parts are written as open surfaces, as stored.
- Steel pieces keep the 4-vertex floor.
- Measured:
  - JHKK 7.331: 920 skipped → 0 (+920 surfaces).
  - 1442_NORTH_SHORE 7.331: 160 skipped reference parts → 4 (+156 parts).

### 2.3 Reference time budget

For a mesh whose faces are at least 40 % repeated, `brep.solid()` now goes straight to the cleaned faces.

- The conform and `drop_covered()` passes (O(faces²)) always fail on such meshes.
- They are what consumed `SDS2_REF_BUDGET_S` on State_Reno (33,261 parts).

Measured on State_Reno 7.331 (78,617 reference placements, same 5,400 s budget):

| | written | budget-skipped |
|---|---:|---:|
| v5.5.3 | 29,182 | 49,027 |
| + patch | 35,974 | 42,631 |

The budget still runs out:

- Every part that does not close is double-sided: 50 % repeated faces and 4-user edges. Sampled cost is 0.26 s per
  part (first sew, cleaned sew, then the open shell).
- The remaining parts need about 2,500 s more.
- So the 7 time-budget models (5 of them lift candidates: B, kkl, dad1, nmb, hjkiu) keep
  `reference_time_budget_exceeded` until `SDS2_REF_BUDGET_S` is raised. That is a fleet setting, left to the fixer and
  owner.

### 2.4 Hollow closed pieces built as filled solids (new)

`brep._nest_voids()` handles a piece whose stored faces form a closed body lying inside another closed body of the
same piece. That inner body is the piece's inner wall:

- v5.4 / v5.5.3 built two filled solids, then rejected the result against SDS2's weight. Data-3 A-Practice 8.007 tank
  shell `SH` (T = 3/8 in) came out at 71x SDS2's weight and was left out as `fallback_over_5x_source_weight`.
- The outer body with the inner one as a void weighs exactly SDS2's number:
  - A-Practice: 5,525.9 lb vs SDS2 5,525.3.
  - 19156_610 7.708 `SH` 2923: 195.15 lb vs SDS2 195.12. Here the inner wall touches the outer one, so the inner
    body is cut from the outer.

Safeguards:

- Only one level of nesting is handled.
- Every vertex of the inner body must be inside or on the outer solid.
- The result must be valid, with volume = outer - inner. Otherwise the bodies are left unchanged.
- No face is added or moved.

The result is SDS2's exact geometry, validated by SDS2's own weight. The projection finds it on:

- A-Practice, UOM Union x3, 2259-OKANA x2 (`126x82 7/8`) and FAN_PIER x7 (v4).
- 19156_610 x6, through the touching-wall case added after the projection run.

### 2.5 Pieces whose table record holds no length, width or weight

`brep_placed()` refused a closed B-rep when the piece table gave nothing to compare it with. Examples:

- THERMOFISHER 7.708: 58 wall plates `FB0x0`.
- 19300 Henderson 7.618 / 7.619: 108 placements of `FB0x0` wedges. With the patch, Henderson goes from 108
  skipped to 0.

The closed, valid, non-flat solid of the piece's own faces is now taken when it agrees with what the record holds:

- A round bar's thinnest extent must equal the diameter in its name, within 10 %.
- A plate must be at least its table thickness.

These pieces are counted in `counts.pieces_exact_without_table_data`. THERMOFISHER goes from 58 skipped to 0.

### 2.6 Rolled pieces whose SDS2 weight is the outlier

The profile extrusion is written, tagged `[approx: …]` like every profile extrusion, when two conditions hold:

- It matches the section's own lb/ft (`job_mtrl`) x the piece-table length within 15 %.
- The piece's vertices span that length within 2 %.

Examples:

- SHOAL_CREEK 7.135: W21x44 x 399.5 in recorded at 42.9 lb.
- BAHA_HOT 7.135: C15x50 x 326.7 in recorded at 175 lb.
- STUART_BRADLEY: W21x50 at 245 lb over 468 in.
- EDWARDS AFB: W24x76 at 39 lb over 346 in.

These pieces stay out of the steel-weight check, because SDS2's number is the outlier. They are counted in
`counts.rolled_sds2_weight_outliers`. With the final tree, SHOAL_CREEK's and BAHA_HOT's ratios equal v5.5.3's.

### 2.7 Source gaps get a precise reason and `needed`

When the job does not hold a piece's geometry, the skip reason now says so. The manifest carries `skipped.needed`,
`skipped.source_absent` and `skipped.source_detail` (piece, name and measured detail).

| reason | test (from the job's own data) | data-3 examples |
|---|---|---|
| `source_piece_file_missing` | there is no `subm/<id>` file. Applies to steel pieces and, new, to reference parts. | GT_Alpha_Phi: 336 RB3/4 / RPL placements. 19156_610: RB1/2. DALLAS LOVE FIELD, SHADOWGLEN, TARRIER, GHT (reference parts, 117 placements). These are partial job folders. |
| `source_piece_has_no_geometry` | no faces and fewer than 4 vertex records, whatever the table holds. When the table has a full size, the detail says "stock size only, no axis or position". | 061219_Temp RB3/8 and Viewer_J RB1/2: 261-byte files holding an identity frame and an empty box. RCMS RB1/2: 0-byte file. GR / CK grating stubs. PL0x… / FL0x0 / BLT stubs. |
| `source_piece_zero_size` | the stored faces are flat, and the table gives a zero length (rolled) or a zero L / W / T; also concrete with T = 0 whose mesh is not a solid | `Conc. 0.0 yards` (34 models), L6x4x5/16 / W21x44 / L1x1x3/16 with L = 0 |
| `source_mesh_open` | the part is stored double-sided and its single side still has boundary edges | vendor meshes (RBWAG, Hilti anchors) |

`grader/optional_grader_build_index.diff` maps `source_*` to `source_data_absent`. Without it, the grader keeps
counting these pieces as `converter_feature | sds2 pieces not built`. The manifests say which they are either way.

## 3. Before / after per job (BOX-C, fleet command `sds2_to_step.py <job> -o X_stage2.step --stage 2 --verify`)

Runs compared:

- **v5.5.3** = the published zip.
- **+ patch** = this patch applied to v5.5.3. It is the tested tree; the final tree differs only as noted below the
  table.
- "+ patch (final, weight tally)" = the final tree, where §2.6 pieces are kept out of the weight check.
- Corpus R = imported reference model.
- "Live result" = the result the grader holds today.

{AB_TABLE}

Notes on the table:

- **Controls:** RMC, WHITE_CASTE, LANDMARK (class 1 A) and profil1 (class 1 R) are identical with the patch: same
  class, solids and weight ratio.
- **888 Boylston and RH_PALO_PRACTICE:** v5.5.3 already builds them. RH_PALO's 784 RB placements belong to a
  `REFERENCE MODEL` member, which 5.5.3 recognises.
  - For the fixer: 160 of them (RB5/8, 1 instance each) are placed at the identical point (1200, 1200, 1200). That is a
    reference-placement decoding question, outside this patch.
- **GT_Alpha_Phi** stays class 0 "broken": 336 of its placed steel pieces have no piece file, more than 5 %. The
  patch names the reason, `source_piece_file_missing`.
- **061219_Temp:** 6 fewer nominal-bolt stand-ins. These bolts are guessed from hole stacks, and the stacks are
  recomputed now that 22 HSS pieces are exact.
- **Two more reference jobs**, from their stage-2 manifests. Their `--verify` read-back on BOX-C was still running at
  hand-off; results land under `ab553/` when they finish.

  | job | v5.5.3 | + patch |
  |---|---|---|
  | FGBVF 7.425 (live: v5.1, 5,619 not built) | 34,553 of 34,663 placements written, 110 skipped; 5,509 open, 1,339 of them face sets | **34,663 of 34,663 written, 0 skipped**; 4,314 open (28 face sets): 1,195 more closed solids |
  | State_Reno 7.331 (time budget) | 29,182 written; 49,027 budget-skipped + 408 not closed | 35,974 written; 42,631 budget-skipped + 12 not closed (§2.3) |

{FINAL_RUNS}

Earlier revision of this patch, on v5.4 (v5.4 vs v5.4 + patch; `data/ab/`). The absurd-extent rows are the cases v5.5.3
now fixes:

{AB54_TABLE}

## 4. All 565 live models: replay of every skipped piece (`data/projection/`)

How the replay works:

- For every live model, the job's piece table, sections and skipped piece files were fetched. Up to 300 unique
  skipped pieces per model were taken, by placements; reference models are sampled and scaled to their placements.
- Each piece then went through the converter's own decision path on v5.5.3 and on v5.5.3 + patch:
  `special_solid` → `brep_placed` → table stand-in → skip reason, `brep_reference` for reference parts, and the §2.6
  rule.
- Not replayed:
  - the 5.5.2 bolt change (it does not skip pieces);
  - the time budget;
  - v4's own builder failures and over-5x decisions. For the 171 v4 rows the v5.5.x re-run decides those.

**394 v5.x models**

The replay does not model the time budget, so the 7 time-budget models (§2.3) are counted separately.

| | v5.5.3 (re-run) | v5.5.3 + this patch |
|---|---:|---:|
| models with no skipped piece left | 107 | **167** |
| models whose remaining skips are all `source_*` (→ `source_data_absent` with the grader diff) | 0 | **104** |
| models with converter skips left | 280 | **116** (60 of them only gratings, item `sds2-grating-cylinders`) |
| models limited by the reference time budget | 7 | 7 (more parts written, §2.3) |
| reference placements still skipped | 928,194 | **10** |
| reference placements written as closed solids | 22,819 | **46,870** |
| reference placements written as open surfaces (as stored) | 2,914,417 | 3,818,550 |
| steel placements newly built (exact B-rep / tagged profile) | 15,458 / 0 | 15,742 / 63 (59 after the full §2.6 rule; PRUDENTIAL's 2 x 2 36WF182 fail its solid-weight half) |
| steel placements tagged `source_*` | 0 | 5,566 |

**The 57 lift candidates**

- With v5.5.3: 32 lose the "pieces not built" flag. 20 keep it, because their single-triangle or degenerate
  reference parts are still dropped. 5 are time-budget models.
- With the patch: 52 lose the flag.
  - **jfkf and vfgrt become class 1.** Every part is a closed solid.
  - The other 50 are written completely, but some of their parts are open surfaces as stored. They stay class 2 under
    `source_data_absent | reference open meshes`: closing them would add faces the source does not have (owner's
    rule).
  - The 5 time-budget models (B, kkl, dad1, nmb, hjkiu) keep the flag until `SDS2_REF_BUDGET_S` is raised.

**171 v4 models** (projection of the v4 skip lists only)

- 14 have nothing left skipped.
- 27 have only `source_*` reasons left.
- 130 still have v4-decided builder failures, which the v5.5.x re-run decides.

**Remaining converter skips (v5.x, after this patch)**

| group | models | placements |
|---|---:|---:|
| gratings `GR` / `GT` (over-5x and open / no B-rep) | 61 + 12 + 7 + 4 | ~1,770 |
| 'ATR 1' all-thread rod: the mesh folds back on itself | 5 | 160 |
| `SH` 537 / 2807 (19156_610): one body at 2.3x SDS2's weight, and an open one | 6 | 18 |
| deck / plate oddities (`CK`, `DK`, `PLG`, `14x6000`, `SD`, `6x447`) | 2-4 each | ~45 |
| 36LH joists over 5x (LUCID) | 2 | 306 |
| `4x4 HINGE`, HSS 'other', DWF parts listed by a steel member, Hilti, `#5E-8` rebar | 1-3 each | ~330 |
| `26 OWSJ` joists (`joist_without_depth`) | 3 | 3 |

## 5. Not fixed

- **Open reference meshes** (50 of the 57 lift models, plus the 5 time-budget models). These are surfaces stored open: flat double-sided sheets,
  tubes without caps, single triangles. They cannot become solids without adding faces. They are written as stored,
  and tagged.
- **Gratings** belong to `sds2-grating-cylinders`.
  - Grating piece files with no faces are tagged here: `source_piece_has_no_geometry`, 21 models.
- **Self-intersecting or self-overlapping SDS2 meshes:**
  - 'ATR 1' (SLC5, 40 placements per job).
  - The 36WF182 end-face outline (PRUDENTIAL).
- **AHU / equipment boxes, PLG, `14x6000`:** SDS2's weight and the stored solid disagree by 4-10x, and there is no
  second source to decide which is right.
- **The 160 coincident RB5/8 reference placements in RH_PALO** (§3): a question about reference placement, not about
  building pieces.
- **`26 OWSJ`:** needs the CISC series added to `joist.DESIG`, in the fixer's joist module.
- **DWF parts that a steel member also lists:** the reference member already writes them; 1 placement, 1442 North
  Shore.
- **The reference time budget:** 7 models, §2.3.
- **`#5E-8` rebar (DMV_BOSK, 184 placements)** closes only with the fixer's `v5work` keyhole / spike `loops_of()`
  draft.

## 6. Fixer drafts read and built on

- **`slot_size_job`** (`v5work/decode/piece_table.py`):
  - It picks the same layout as `slot_size()` on all 124 job folders fetched on BOX-C for this item (every model of
    the A/B sets and diagnostics).
  - No v5.x skip list among the 565 shows the phantom-piece signature (one-character names on steel pieces). That
    signature appears only in v4 rows of 7.425 reference-style jobs, which v5.x reads as reference members.
  - Its case is `test_4b7e6e` 8.004, which is currently class 2 `members_only_stage1_fallback` (stage 2 weight
    mismatch from phantom placements) and is not a "pieces not built" model. The `sds2-weights-failures` item also
    points to this draft for that job.
  - It is shipped unchanged as `sds2-slot-size-job.optional.diff`.
- **brep `loops_of()` spike / keyhole draft:** independent of this patch. Together they also close DMV_BOSK `#5E-8`.
- **Hooked-anchor B-rep first:** needed the shared-tuple `_absurd()` fix. v5.5.3 has it.

## 7. Overlaps with other pfix patches (checked with `patch` on v5.4)

- **sds2-grating-cylinders:** clean in both orders.
- **sds2-weights-failures:** one rejected hunk. Both patches fix `_absurd()`; keep either.
- **sds2-approx-pieces-7x:** context-only conflicts.
  - That patch also does not apply cleanly to the pristine v5.4 base on its own.
  - It restructures `brep.solid()` into `_passes()` / `_repaired()`. Put this patch's two `clean_faces` hooks at the
    start and the end of `_passes()`.
  - Keep both blocks of module constants after `HOLES_NOT_CUT`, and both manifest additions.
  - `_nest_voids()` and `_solid_parts()` are untouched by that patch.
- **On v5.5.3:** this patch is the only one rebased so far. The others are still vs v5.4.
