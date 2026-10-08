# Adversarial review: sds2-approx-pieces-7x

**Verdict: confirmed with caveats.**

On its stated base (v5.5.3), the patch does what it claims:
- the before/after numbers reproduce exactly;
- it adds no face and loses no exact piece;
- it creates no invalid solid and leaves the class-1 controls byte-identical.

The caveats concern integration and the size of the lift, not correctness:
1. The diff does not apply to the current SDS2 build (v5.5.6), which already ships overlapping code.
2. Measured against v5.5.6, the class-1 lift is 2 models, not 4.
3. The tube identity (F) is described wrongly and lacks a length check.

All compute ran on BOX-C (SDS2) and BOX-A (one IFC probe). Scripts are in `review/scripts/`, results in `review/data/`,
and raw outputs in `s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-approx-pieces-7x-review/`
(`out/<variant>/<job>/`, `audit2/`).

## What was checked

- **Patch integrity.**
  - The v5.5.3 zip's sha256 is `706e1289…5cc0a9`.
  - The diff applies cleanly to v5.5.3 with both `patch -p1` (Mac) and `git apply` (BOX-C).
  - The result is byte-identical to `patch/brep.py` and `patch/to_step2.py`, and to the copies uploaded to S3.
- **Variants.**
  - `base553` is v5.5.3.
  - `cand` is v5.5.3 plus the diff.
  - `v556` is v5.5.6 alone, for reference.
  - Each conversion ran `sds2_to_step.py --stage 2 --verify` with the SDS2 fixer's env (`/work/agentwork/sds2v54/env`), 14 at a time.
- **Conversion comparison** (`cmp_conv.py`).
  - Placement by placement on (member, piece, instance) from `_pieces.csv`: lost / new placements, builder transitions, moved
    origins.
  - From the manifest: class, read-back (valid / top-level shapes), steel ratio, family ratios and stand-in types.
  - A full manifest deep-diff on the controls.
- **Independent piece audit** (`audit.py`, 27 jobs).
  - `brep_placed()` runs per unique placed plate / rolled / BLT piece, in a separate process per variant.
  - Checks:
    - a piece exact in base must stay exact;
    - a piece exact in both must have the same volume and face count;
    - **no-fabrication test** for every piece newly exact in cand. The solid is triangulated, and every triangle centroid
      must lie on a face the piece file stores: same plane within 0.003 in, and inside the face by the even-odd rule on its
      full stored entry list. This test is independent of the patch's own loop reading.
  - **Calibration:** the same test on pieces exact in both variants gives 0 uncovered (no false positive). The same solids
    shifted 0.05 in give 0.56-1.0 uncovered. 403 of the 405 samples are ≥ 0.84; the two lower ones are faces parallel to
    the shift.

## Results

### A. The author's own claims, re-run (v5.5.3 → patch)

| job | approx | class | read-back valid / shapes | steel |
|---|---|---|---|---|
| 10 World Trade 7.619 | 975 → 0 | 2B → 1A | 5,204 / 5,204 both | 1.0151 → 1.0155 |
| IFC_MHP 7.708 | 3 → 0 | 2B → 1A | 8,428 / 8,428 both | 1.0108 → 1.0107 |
| Revit_MHP 7.708 | 6 → 0 | 2B → 1A | 16,850 / 16,850 both | 1.0106 → 1.0105 |
| 401 CONGRESS 7.613 | 2 → 0 | 2B → 1A | 3,934 / 3,934 both | 1.0112 both |
| P545 7.135 | 50 → 2 (plus 158 joist stand-ins, unchanged) | 2B both | 51,803 → 52,133, all valid | 1.0009 both |

All five match the README exactly. The extra P545 shapes are SDS2 bolts (620 → 699) and nominal bolts (+31, tagged).
They come from the hole records of the newly exact pieces; boolean hole failures fall 935 → 876.

### B. Different real models (not in the author's 42-job sample)

| job | approx | class | read-back |
|---|---|---|---|
| MOHAN 7.425 (385 MB) | **300 → 61** | 2B both | 13,068 / 13,068 both |
| TEST_4d9118 7.425 | 49 → 34 | 2B both | 4,633 → 4,634, all valid |
| SAN_YSIDRO 7.135 | 14 → 0 | 2B both (bolt records absent) | 841 → 877, all valid |
| TEST_JOB 357e8c 7.619 | 5 → 0 (7 negative-weight pieces at 1.000-1.015x) | 2B both | 84,030 both |
| 18SEPT ABM 7.243 | 3 → 0 | 2B both | 5,967 both |
| MHP_JOB_ABM 7.708 | 2 → 0 | 2B both | 4,003 both |
| TEXAS-RTE 8.007 | 1 → 0 | 2B both | 503 both |
| TEST_10-15-2022 8.004 (its only blocker is approx pieces) | 17 → 16 | 2B both | 114 both |
| CVS 7.132, TEMP1 8.004, white_castle-2 7.312, BACKUP_ITB 7.613, MISC_5_SONIC 7.323 | unchanged (1, 1, 1, 1, 10) | 2B both | identical |

- No placement was lost or moved, and no exact piece became approximate.
- TEST_10-15-2022 stays class 2: its 16 remaining placements are one GT1x12 grating tread (the grating item's).
- Conversion wall time over 25 jobs: median 1.02x, total +1.5%. The worst case is 1086-LA, 84 → 123 s.

### C. Class-1 controls (7.135, 7.200, 7.312, 7.425, 7.619, 7.708, 8.007)

The controls are RMC, MVK, 14-Mt Carmel, Chennai Ella Barnes, PROCTOR & GAMBLE, 1086-LA Technology and LANDMARK CENTER 03012023.
- All are identical before and after: manifest (0 differing keys), `_pieces.csv` and `_skipped.csv` byte-identical, and the
  same read-back.
- The 5 jobs above with no new exact piece are identical in the same way.

### D. Piece audit, 27 jobs (A + B + C + DSCC 7.312, SOCORRO 7.425)

| check | result |
|---|---|
| pieces exact in v5.5.3 that the patch loses | **0** |
| exact pieces whose volume / face count changes | **0** |
| newly exact pieces / placements | 471 / 1,319 |
| newly exact pieces with any area not on a stored face | **0 of 471** (max uncovered fraction 0.0) |
| newly exact pieces that are BRepCheck-invalid | **0** |
| repair kinds seen | keyhole split, coplanar merge, zero-width face drop, isolated face drop, 0.001-in weld |

The audit finds no fabricated geometry.

Tags are removed only with evidence:
- Repaired pieces still pass v5.5.3's own weight test. Their ratios are 0.98-1.05, and 0.99-1.27 for the 10 World Trade HSS.
- Identity-accepted pieces are listed in `brep_repairs.weight_unvalidated` with their evidence.
- On SAN_YSIDRO every recorded piece weight is exactly 27.94 lb/in x L, whatever the section (W250x18, W460x52,
  W530x66). Those weights are an artifact, and the B-reps match their own section's lb/ft at 1.01-1.04x.
- GR panels closed by the repair stage keep the `grating_solid_panel` stand-in tag (TEMP JOB, from the author's own run).

## Caveats (ranked)

1. **Stale base; the diff does not apply to the current build.**
   - v5.5.4 (21:54), v5.5.5 and v5.5.6 (22:33 local) were all in `_control/z3conv/sds2/` before this README was
     finished (00:07). The deliverable's "v5.5.3 is the newest SDS2 build" is wrong, and BOX-C is already running v5.5.7
     drafts.
   - On v5.5.6, 2 of 3 brep.py hunks and 4 of 7 to_step2.py hunks fail.
   - v5.5.4 merged exactly what this README says not to stack the patch on: the always-on `_drop_spikes` /
     `_split_keyhole` and ring-cap drop. It also merged `_section_ok`, which overlaps E/G, and open-rim surfaces.
     v5.5.6 merged the grating builder, which the repair stage's GR closing now competes with.
   - A rebase needs design decisions, not fuzz. **Supporting evidence for doing it:** my v5.5.6 audit confirms the author's
     warning. The always-on split loses **DSCC W10x12 #5513** and **SOCORRO HSS5x2x5/16 #3492**, which are exact in
     v5.5.3 and in the patch. That is a live regression in v5.5.4+, and moving the split into the repair stage (this
     patch's design) fixes it.
   - Unrelated, also found: v5.5.6 loses SAN_YSIDRO PL8x196 7/8 and PL8x429 3/4 through its "piece-table entry unreadable"
     rule.

2. **The class-1 lift is 2 models against the current pipeline, not 4.**
   - **401 CONGRESS** is already 1A with v5.5.6 alone (approx 2 → 0). The lift is not this patch's.
   - **10 World Trade** cannot lift in the grader. Its live grade already carries "section families off the SDS/2 weight
     by > 5%: HSS" (HSS 1.058 in v5.5.3). The patch makes HSS 1.077, and v5.5.6 alone gives 1.089, with 526 placements as
     `brep_open_surface`. The patch does close all 549 placements that v5.5.6 leaves open or extruded.
   - **IFC_MHP and Revit_MHP** stay 2B with v5.5.6 alone (3 / 6 extrusions). The patch makes them 1A, with HSS family
     1.0095 → 1.0071. These are the item's real lifts.
   - On MOHAN, v5.5.6 alone already makes 239 of the patch's 241 new placements exact, and on TEST_10-15-2022 1 of 1. The
     incremental gain over v5.5.6 is concentrated in the 7.6xx first-vertex keyhole (A), the coplanar merge, and the
     identity / negative-weight rules.
   - The README's "about 3-4 class-1 lifts" should read about 2.

3. **Tube identity (F): the rationale is wrong and the rule is loose.**
   - The MHP pieces 697 / 698 / 700 are not HSS "rolled to a 144-in radius" with "length between chord and half circle".
   - Slab cuts show a nearly constant section of about 8.0 in2 along x. The tube is sloped about 10.5 degrees in its local
     frame and only slightly curved.
   - Volume / area (249.8 in) is *below* the 282.3-in chord. The bound `0.85 x (chord - side)` lets that through, and the
     branch has no table-length check, unlike the straight branch. Here the table L = 282.333 equals the B-rep x extent.
   - The acceptance itself is corroborated independently. SDS2's own IFC export of the same project (BOX-A,
     `MHP_JOB_031920.ifc`, members ts1196 / ts1194 / ts1203) has the same envelopes (6 x 283.2 x 33.7 in vs
     6 x 285.9 x 33.8 in), and B-rep volumes of 0.91-0.95x the IFC volumes. In the IFC, SDS2's Material_Net_Weight equals
     its geometry (0.993x), so the 2018 piece-table weight (0.387x) is the outlier.
   - Recommended:
     - add `|ext[0] - L| <= 2 % + 0.05 in` to the tube branch (it keeps all 3 MHP pieces);
     - fix the comment and README wording.

4. **The identity rules (E/G) have no bound on the weight disagreement.** MOHAN HSS8x4x1/4 pieces at 336x and 2,231x
   SDS2's weight are accepted on section envelope + lb/ft + length ≤ L. This is consistent with v5.5.4's merged
   `_section_ok` policy, but the two should be merged into one rule when rebasing.

5. Minor:
   - The plate identity accepts on thickness alone when the table lacks L or W.
   - `solid()` now also catches exceptions from the first pass. That only changes the reason label.

## Not verified / limits

- TEMP JOB RGK and RH Jacksonville were not re-run; they hit the 4-hour cap or take more than 2 hours.
- The grader itself was not run. The lifts are converter-manifest classes plus the live fix-plan blockers.
- **Clean-up is incomplete.** The annotationprod SSO session expired during the review (needs an interactive
  `aws sso login`), so SSM was unavailable for the final step.
  - All my processes had finished, and every STEP was deleted by `conv.sh` after its upload.
  - Still on BOX-C: `/work/agentwork/sds2-approx-pieces-7x-review/` (jobs, about 4.6 GB, trees, audit JSON).
  - Still on BOX-A: `/work/agentwork/sds2-approx-pieces-7x-review/mhp.ifc` (43 MB).
  - Both should be removed (`rm -rf` of those two folders) once SSM works again.
