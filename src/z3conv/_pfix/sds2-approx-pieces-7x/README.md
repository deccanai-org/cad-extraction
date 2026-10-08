# sds2-approx-pieces-7x: exact B-rep for the "sds2 approx pieces" on SDS2 7.x / 8.0

**Base: `sds2-step-pipeline-v5.5.3.zip`**, the newest SDS2 build in `s3://annotationprod/cad-disk-extract/_control/z3conv/sds2/`
(sha256 `706e1289…5cc0a9`, copy in `base553/`). The item named v5.4. v5.5.3 is a later release of the same line and
the patch applies to it cleanly. v5.5.3 already routes `REFERENCE MODEL` members to the reference path, so the
previous run's special case for them is gone from this patch.

The previous run of this item made `patch/superseded_v54/` (a diff against v5.4, used for `cand5`). This run kept its
repair stage and added five fixes. The new diff is against v5.5.3.

| file | what |
|---|---|
| `patch/sds2-approx-pieces-7x.diff` | **The patch.** A unified diff against v5.5.3 that changes `decode/brep.py` and `decode/to_step2.py`. Apply it with `patch -p1` in the folder that holds `sds2-step-pipeline/`. It also applies to v5.5.0 / v5.4.1 except one `reset()` hunk, which needs a hand merge because those builds have no `REF_FACES`. |
| `patch/brep.py`, `patch/to_step2.py` | The patched files. |
| `patch/superseded_v54/` | The previous run's diff against v5.4, and its increment over the SDS2 fixer's `v5work` draft. Superseded. |
| `base553/` | The base: the v5.5.3 zip and its CHANGES. `base54/` and `base/` (v5.3) are the bases of earlier runs of this item. |
| `job/` | Every script that ran on BOX-C: the diag, the hole and marker scans, the probes and the conversion drivers. |
| `data/` | Per-job diag summaries, the version table and the conversion comparison (JSON / text). |

The CLI and the outputs are unchanged. The manifest gets one new top-level key, `brep_repairs`, which `classify()`
does not read. It has three lists:
- `repaired`: pieces closed by the repair stage, with the fix that was needed;
- `weight_unvalidated`: pieces kept on an identity check, with the evidence;
- `negative_weight`: pieces whose SDS2 weight is stored with a negative sign.

The log's `solids:` line gets three counters: `exact_brep_repaired`, `exact_brep_weight_unvalidated` and
`exact_brep_negative_weight`.

Do **not** stack this patch on the SDS2 fixer's `v5work` `brep.loops_of` draft. This patch already contains that
draft, generalised and moved into the repair stage.

## Results

### Per version: placed pieces left to the approximate builders (diag, 42 jobs, 7.132 to 8.004)

`diag.py` counts every placed plate / rolled / BLT piece whose exact B-rep `brep_placed()` rejects. Such a piece is
written by an approximate builder: `plate_from_vertices`, `rolled_profile_extrusion` or `piece_table_standin`. In the
grade these are the "sds2 approx pieces".
- **Before** is v5.5.3 unchanged. **After** is v5.5.3 with this patch.
- "grating (other item)" covers GR / GT pieces; the `sds2-grating-cylinders` patch builds those.
- "file has no faces" covers piece files that hold no face topology (see "Not fixable").
- **rest** is what this item can address.

| SDS2 | jobs | placed plate / rolled / BLT pieces | approximate before → after | grating (other item) | file has no faces | **rest (this item)** |
|---|---|---|---|---|---|---|
| 7.1 | 5 | 43,016 | 196 → 54 | 8 → 8 | 0 → 0 | **188 → 46** |
| 7.2 | 3 | 35,731 | 609 → 575 | 457 → 457 | 0 → 0 | **152 → 118** |
| 7.3 | 13 | 144,884 | 1,430 → 776 | 858 → 346 | 4 → 4 | **568 → 426** |
| 7.4 | 4 | 37,856 | 421 → 171 | 1 → 0 | 0 → 0 | **420 → 171** |
| 7.5 | 1 | 6,614 | 448 → 436 | 97 → 90 | 298 → 298 | **53 → 48** |
| 7.6 | 7 | 111,730 | 2,197 → 1,134 | 121 → 116 | 944 → 944 | **1132 → 74** |
| 7.7 | 7 | 28,141 | 980 → 825 | 661 → 640 | 0 → 0 | **319 → 185** |
| 8.0 | 2 | 8,684 | 909 → 358 | 117 → 109 | 172 → 172 | **620 → 77** |
| all | 42 | 416,656 | 7,190 → 4,329 | 2,320 → 1,766 | 1,418 → 1,418 | **3,452 → 1,145** |

No job lost an exact piece: the exact count went up or stayed the same in all 42 jobs (`data/table_jobs.md`).

Per job: `data/table_jobs.md`. Raw diag summaries: `data/diag/<run>/<variant>__<job>.json`. The runs are:
- `d11` / `d9b` / `d10` / `d10b`: before (`base553`);
- `d9`: after, as `cand8` = this patch without F;
- `d12` / `d10b` / `d10c`: after, as `cand9` = this patch. `cand9` differs from `cand8` only by F.

### Conversions: `sds2_to_step.py --stage 2 --verify`, v5.5.3 vs v5.5.3 + patch (BOX-C)

Columns:
- **approx**: placements tagged `plate_from_vertices`, `rolled_profile_extrusion` or `piece_table_standin`, plus
  member envelopes, as listed by `manifest after read-back`.
- **read-back**: BRepCheck-valid shapes / top-level shapes in the final read-back, after v5.5.3's own read-back
  repair pass. Open reference surfaces count as valid shapes.
- **steel**: STEP steel / SDS2 piece weights.

| SDS2 | job | approx before → after | class | read-back BRep-valid / top-level shapes before → after | steel | exact via repair / identity / negative weight | wall s |
|---|---|---|---|---|---|---|---|
| 7.132 | METHODIST_JOB_8164be | **50 → 6** | 2B → 2B | 12,386/12,386 → 12,386/12,386 | 1.007 → 1.007 | 44 / 0 / 0 | 838 → 850 |
| 7.135 | P545_HANGAR_JOB_15bf82 | **50 → 2** | 2B → 2B | 51,803/51,803 → 52,133/52,133 | 1.001 → 1.001 | 48 / 0 / 0 | 1258 → 1439 |
| 7.245 | CLAYTON_JOB_8eda68 | **88 → 54** | 2B → 2B | 48,547/48,547 → 48,637/48,637 | 1.023 → 1.023 | 33 / 0 / 1 | 2190 → 2930 |
| 7.312 | DSCC_JOB_ef345b | **64 → 64** | 2B → 2B | 17,013/17,013 → 17,013/17,013 | 1.018 → 1.018 | 0 / 0 / 0 | 1025 → 1121 |
| 7.312 | DUPONT_JOB_052713.zip__61ab8f | **155 → 87** | 0 broken → 0 broken | 57,367/57,418 → 57,379/57,430 | 1.023 → 1.023 | 52 / 0 / 16 | 4368 → 4210 |
| 7.331 | 19-519_CMS_Job_0a4016 | **147 → 108** | 2B → 2B | 90,482/90,482 → 90,536/90,536 | 1.0 → 1.0 | 12 / 27 / 0 | 3743 → 3725 |
| 7.336 | 17-006_LEWISMISC_JOB_5f7b3e | **141 → 140** | 2B → 2B | 3,609/3,609 → 3,609/3,609 | 1.013 → 1.013 | 1 / 0 / 0 | 536 → 586 |
| 7.425 | RH_Jacksonville_-Grand_Stair_JOB__TRAI | **242 → 8** | 2B → 2B | 63,613/63,613 → 63,613/63,613 | 1.005 → 1.004 | 210 / 24 / 0 | 8847 → 8455 |
| 7.425 | SOCORRO_ISD_JOB_8566ee | **154 → 151** | 2B → 2B | 54,728/54,728 → 54,728/54,728 | 1.01 → 1.01 | 3 / 0 / 0 | 1794 → 1817 |
| 7.516 | Centene_University_JOB_20c7f1 | **426 → 414** | 2B → 2B | 47,277/47,277 → 47,277/47,277 | 1.043 → 1.043 | 7 / 5 / 0 | 1436 → 1472 |
| 7.613 | 401_CONGRESS_ST_REVIT_MODEL__JOB_69397 | **2 → 0** | 2B → 1A | 3,934/3,934 → 3,934/3,934 | 1.011 → 1.011 | 2 / 0 / 0 | 979 → 1025 |
| 7.613 | SUSQUEHANNOCK_HS_JOB_12d47b | **43 → 14** | 2B → 2B | 69,289/69,289 → 69,349/69,349 | 1.033 → 1.034 | 1 / 28 / 0 | 1533 → 1434 |
| 7.619 | 10_World_Trade_07-16-21_c5f1d1 | **975 → 0** | 2B → 1A | 5,204/5,204 → 5,204/5,204 | 1.015 → 1.015 | 975 / 0 / 0 | 615 → 603 |
| 7.619 | Kerman_ES_06-10_Job_cb63f0 | **33 → 22** | 2B → 2B | 74,252/74,252 → 74,252/74,252 | 1.026 → 1.026 | 11 / 0 / 0 | 1961 → 1883 |
| 7.708 | IFC_19189_American_Prep_Misc_JOB_bf938 | **110 → 8** | 2B → 2B | 10,900/10,900 → 10,900/10,900 | 1.012 → 1.01 | 102 / 0 / 10 | 987 → 1313 |
| 7.708 | IFC_MHP_JOB_1f2578 | **3 → 0** | 2B → 1A | 8,428/8,428 → 8,428/8,428 | 1.011 → 1.011 | 3 / 3 / 0 | 426 → 369 |
| 7.708 | Revit_MHP_JOB_4a9554 | **6 → 0** | 2B → 1A | 16,850/16,850 → 16,850/16,850 | 1.011 → 1.011 | 6 / 6 / 0 | 537 → 461 |
| 7.708 | THERMOFISHER_JOB_bff8f8 | **37 → 26** | 2B → 2B | 34,277/34,277 → 34,289/34,289 | 1.008 → 1.008 | 11 / 1 / 0 | 645 → 758 |
| 8.004 | PSU_BNR_JOB__mallesh__4e9908 | **258 → 248** | 2B → 2B | 21,374/21,374 → 21,391/21,391 | 1.019 → 1.019 | 10 / 1 / 0 | 1089 → 1172 |
| 8.004 | TEMP_JOB_RGK_3adae7 † | **585 → 45** | 2B → 2B | 75,380/75,451 → 75,424/75,495 (after repair pass 1; 71 invalid in both) | 1.087 → 0.994 | 540 / 0 / 0 | > 14,000 both (cap) |

† TEMP JOB RGK (8.004, 2.3 GB STEP):
- Both variants hit the 4-hour cap during v5.5.3's second read-back repair pass. Two read-backs and one repair pass
  completed in each.
- The read-backs match in both variants:
  - first read-back: the same 519 invalid, for example `PIPE 1 1/4 STD`, `MC18x45.8` and `REFERENCE MODEL`
    reference parts;
  - after repair pass 1: 71 invalid.
- None of them is a piece this patch builds.
- approx counts `plate_from_vertices` 315 + `rolled_profile_extrusion` 263 + `member_envelope` 7 before, and 38 + 7
  after.

DUPONT 7.312 is class 0 in **both** variants. v5.5.3 already writes 51 unnamed solids that read back invalid;
the patch adds none (51 → 51).

Converter class 1 lifts:
- 10 World Trade 7.619 (see the HSS family-weight note below);
- IFC_MHP 7.708 and Revit_MHP 7.708, whose only blocker was this item;
- 401 CONGRESS 7.613, whose only blocker was also this item.

**The 9 models on 7.x / 8.0 whose only class-1 blocker in `class2_fix_plan.json` is "sds2 approx pieces":**

| Outcome | Models |
|---|---|
| Lifted | IFC_MHP, Revit_MHP, 401 CONGRESS |
| Already exact in v5.5.3 itself | IFC_RH Palo |
| Not lifted | 50 Binney 7.245 (PL1x0) and SAN MARCOS 7.331 (3 plates): their outlines cross themselves |
| Not lifted | ABCD 7.425: B-rep twice the table length, weight -0.132 |
| Not lifted | BAPTIST 7.135: 17 → 5, the rest have over-used edges |
| Not lifted | LANDMARK CENTER 8.007: piece file missing |

Regression controls (DSCC 7.312, SOCORRO 7.425): their exact pieces are unchanged and every read-back is identical.
These are the two pieces the draft's always-on keyhole split had broken (DSCC W10x12 #5513, SOCORRO
HSS5x2x5/16 #3492).

## Why approximate pieces had no exact B-rep, and what this patch changes

### How the cases were found

`job/diag.py` runs `brep_placed()` on every placed plate, rolled piece and BLT piece of a job. For each rejected
B-rep it records:
- the reject reason;
- the edge-use histogram, before and after `conform()`;
- the faces that fail to build;
- the free edges after sewing;
- a dump of the raw vertices and faces (pieces with up to 600 vertices).

`job/holes_scan.py` re-applies the repair edits to the pieces that still fail and classifies the defect that is
left. `job/marker_match.py` checks whether a kind-7 (marker) face record covers each remaining hole.

Coverage: 42 jobs, SDS2 7.132 to 8.004.
- 35 data-3 jobs.
- 7 jobs from the SDS2 fixer's draft set: METHODIST, LEWISMISC, Queen Street, COCA COLA, CONTRA SAB, INOVA, SUNNY.
  These were read in place, read-only.
- Of the data-3 jobs, 8 are models whose only class-1 blocker is "sds2 approx pieces": IFC_MHP, Revit_MHP,
  401 CONGRESS, IFC_RH Palo, 50 Binney, SAN MARCOS, ABCD, BAPTIST.

### Root causes fixed

Every fix uses only data the job holds. No face is ever added, so open meshes stay open.

All the fixes run only after the v5.5.3 code has rejected the piece:
- Stored faces are first tried as v5.5.3 tries them: as stored, then `conform()`, then `drop_covered()`. The repair
  stage runs only when all of those fail.
- The identity checks and the negative-weight check run only where the v5.5.3 weight / size test would reject the
  B-rep.

So no piece that v5.5.3 builds changes; this is guaranteed by construction. The diag runs confirm it: no job lost an
exact piece.

**A. Keyhole bridge from the face's first vertex** (new; 7.4xx to 8.0xx; the largest new class).
- A hollow-section end face is stored as one entry list: outer corner, bridge to an inner corner, inner ring, bridge
  back to the first vertex, rest of the outer ring. Example: 10 World Trade 7.619 HSS8x4x3/8 `[4, 1, 0, 5, 6, 1, 4, 7, 8, 9]`.
- `loops_of()` closes a loop whenever the first vertex comes back. So it read a non-simple loop `[4, 1, 0, 5, 6, 1]`
  plus a triangle `[7, 8, 9]`. 3 or 6 edges stayed free and every such HSS fell back to an extruded profile.
- The draft's keyhole split could not fix this, because the split had already happened inside `loops_of()`.
- Fix (repair stage only): a return to the first vertex that comes straight back along the loop's first edge
  (`cur[-1] == cur[1]`) is a bridge, not a loop end.
- Result:
  - 10 World Trade 7.619: 975 → 0 approximate placements;
  - IFC_19189 7.708: 110 → 8;
  - also TEMP JOB RGK 8.004, RH Jacksonville 7.425 and METHODIST 7.132.

**B. Bridges and touching loops cancelled across the whole face** (new; generalises the SDS2 fixer's draft).
- `_cancel_bridges()` works on all the loops of one face. It drops edges that are stored once in each direction:
  - keyhole bridges;
  - zero-width spikes `a → b → a`;
  - an inner ring running along the outer ring. Kerman 7.619 HSS5x3 end faces have the top wall cut away; after the
    T-junction split in `conform()`, the shared top edge is a pair of opposite edges.
- It then chains the remaining edges in stored order.
- The face covers exactly the same points as before, because a slit has no area.
- This replaces the draft's `_drop_spikes` and `_split_keyhole`. Those split only at the first opposite pair and kept
  the closing vertex twice.

**C. Overlapping coplanar patches, zero-width flaps, kind-0 marker faces, micro-gaps, ring caps** (previous run).
These are kept unchanged:
- `merge_coplanar` (P545 7.135 cope / notch ends);
- `drop_slivers`;
- `drop_isolated` (bent-plate mid-surface marker stored with kind 0: TEMP JOB 8.004, RH Jacksonville 7.425);
- `weld` at the sewing tolerance (DUPONT 7.312);
- the ring-cap rule in `drop_covered`.

See `patch/superseded_v54/` and the code comments for the evidence.

**D. Negative SDS2 piece weights** (new).
- Some 7.1xx to 8.0xx piece tables store the weight with a negative sign. Examples:
  - CLAYTON 7.245: W24x55 and W16x26;
  - DUPONT 7.312: C10x15.3 stair pieces;
  - IFC_19189 7.708: MC12x10.6.
- On 47 of the 47 such pieces that close, in 14 jobs, the magnitude equals SDS2's weight of the stored B-rep at
  1.000x (`job/p4.py`).
- v5.5.3 treated these pieces as weightless. The table extents then often disagreed, for example CLAYTON W24x55
  with L = 5,117 in, so the B-rep was dropped.
- Fix: accept the B-rep when its weight is 0.98 to 1.02x the magnitude.
- The other negative values are tiny constants (-0.189, -0.49, -0.043 lb). They fail this test and are handled as
  before.

**E. A wrong lb/ft in the section's own job_mtrl record** (new).
- Example: 19-519 CMS 7.331 custom section HSS1.5x13GA.
  - The record holds d = 1.5 in, t = 0.0897 in, which gives 1.35 lb/ft.
  - The same record says 3.0 lb/ft.
  - SDS2 weighs each piece as 3.0 lb/ft × length, so every B-rep looked 0.45x too light.
- The B-rep's own wall, 2 × volume / surface, is 0.089 in.
- Fix: `_stock_identity()` for rolled pieces also accepts a B-rep whose mean cross-section is 0.85 to 1.1x the area
  computed from the record's own dimensions (`_section_area`). The section-envelope test is still required.

**F. Curved hollow sections** (new).
- Revit_MHP and IFC_MHP 7.708 have HSS6x4x1/2 rolled to a 144-in radius. These 3 + 6 placements are the models'
  only class-1 blocker.
- Their faceted B-rep closes (Revit_MHP only after the repair stage).
- The recorded weight matches neither the length nor the arc: the B-rep is 2.58x.
- Fix: accept a tube of any path when all of these hold:
  - its wall, 2 × volume / surface, is 0.85 to 1.1x the section's own wall. Here it is 0.463 in = 0.93 × 1/2 in. A
    hollow section closed as a bar would be about 4x;
  - its thinnest extent is a side of the section (6.000 in);
  - its length, volume / section area, lies between the chord and a half circle over it.
- Revit_MHP goes from 6 approximate placements to 0.

**G. Previous run's stock identity** (kept): a flat plate of the table thickness within its L x W stock, or a straight
rolled piece within the section envelope at 0.6 to 1.6x the section's lb/ft (SUSQUEHANNOCK 7.613, PSU BNR 8.004).

**Removed from the previous run:** the `REFERENCE MODEL` member rule. In v5.5.3 those members never reach
`brep_placed()`, so the rule was dead code.

### Overlaps with other patches

- **sds2-grating-cylinders.** Its patch also edits `to_step2.py`, in `convert()`, on the special-piece path and in
  the grating builder. The two patches do not touch the same lines: this one edits `brep_placed()`,
  `_stock_identity()`, the `solids:` counters and the manifest tail. Expect fuzz, not conflicts.
  - Interaction: the repair stage (`drop_isolated`) now closes many **GR panels**. They are written with SDS2's own
    bar B-rep, at 0.86-0.98x SDS2's grating weight. Example: SLC5 7.331, 389 → 24 approximate placements.
  - v5.5.3 still tags every exact GR / GT B-rep as `bar grating written as SDS2's solid panel`. That label belongs to
    the grating patch, which should drop it for these pieces.
- **SDS2 fixer `v5work`.** This patch contains the `brep.loops_of` spike / keyhole draft, generalised and limited
  to the repair stage. The `special_solid` and `piece_table` drafts are untouched.

## Not fixable here: the source lacks the data, or it is the owner's rule

These are the remaining non-grating approximate placements in the 42 jobs, from `data/data_remaining.json`. They come
from `job/holes_scan.py` and `job/marker_match.py`, which were re-run with the patched decoder.

- **The piece file stores no face for part of the boundary: 519 placements, 264 pieces.**
  - What remains open after all the edits is one or more closed, planar free-edge loops.
  - Examples:
    - the mitred end of the web of BG Residential 7.331 W12x35;
    - the flange underside across a coped web of Nantucket 7.312 W16x100 (138 placements, the whole job's rest);
    - THERMOFISHER, Marist, 1544 Cats Rail.
  - `marker_match.py` found **no** kind-7 marker face covering any of these holes, in 13 jobs. The face is simply
    not in the file.
  - Closing it would add a face, so this is the owner's decision.
  - If the owner allows "close a planar hole bounded by stored edges", the hole loops are already listed per piece in
    `holes9/<job>.json` on S3.
- **Overlapping or interpenetrating sub-bodies: 434 placements, 173 pieces.** Free and over-used edges remain together.
  - Turnbuckles, SOCORRO 7.425 TB5/8x6, 120 placements: the hex body and side bars are stored as one mesh that
    cuts through itself.
  - Kerman 7.619 HSS ends with slotted knife-plate cuts.
  - Faceted pipe rails with failed faces.
  - Separating them needs a boolean union of bodies the file does not delimit.
- **Closed topology, but the stored solid intersects itself: 128 placements, 72 pieces.**
  - Stair channels, for example DUPONT 7.312 C10x15.3 and SUNNY / INOVA C12x20.7: the skew end cut crosses the
    opposite square end. This leaves an inverted sliver up to 0.1 in thick.
  - Plate outlines that cross themselves: SAN MARCOS 7.331 PL1x17 3/4 / PL1x36 (3 pieces) and 50 Binney 7.245
    PL1x0. Both are models whose only blocker is this item.
  - Clipping the sliver would be a geometric decision about what SDS2 meant.
- **Piece file holds no faces: 1,418 placements.**
  - 216-byte or 261-byte stubs: identity frame, an empty ±240,000 bounding box, and the pipe radius or 1.5. They
    hold 0 vertices and 0 faces. Mostly `PIPE 1 1/4 STD` rails (Centene 7.516, S8 Extrusion / MILL OFFICE /
    STOCKTON 7.613, PSU BNR 8.004).
  - 388 to 1,156-byte files that hold only hole records (Parkview 7.613 L6x6x3/8).
  - SDS2 never generated these solids, so the converter's nominal / profile stand-ins are all the job supports.
  - Corpus: "piece file has no readable face topology" covers about 14,000 placements in 42 class-2 models.
- **Piece file missing (`subm/<id>` absent): about 10,300 placements in 20 class-2 models in the corpus.** These are
  partial extractions, for example LANDMARK CENTER 8.007.
- **Closed B-rep, but the weight / size test fails and no identity check holds: 56 placements, 26 pieces.**
  - LEBANON 7.135 BNT bent plates are 1.8-5.5x SDS2's weight. The weight sits below even half the L x W x T stock,
    while the B-rep sits within it.
  - Queen Street 7.708, 15 pieces.
  - STOCKTON DK2x36 deck pieces are 1.8x.
  - ABCD 7.425 PL1/4x5 5/16: the B-rep is 116.5 in long, twice its 62.8-in table length, and its weight is garbage
    (-0.132).
  - Accepting these would need evidence the job does not give.
- **Out of scope:**
  - grating GR / GT: 1,766 placements left, handled by the `sds2-grating-cylinders` item;
  - 6.x jobs (defaultAdapt 6.322).

**Grader note: HSS family weight.**
- SDS2 draws HSS B-reps at the *nominal* wall with sharp corners. Example: 10 World Trade HSS8x4x3/8 has a 0.375-in
  wall.
- SDS2's lb/ft uses the AISC *design* wall, 0.93 t.
- So exact HSS weigh about 7.5% more than SDS2's numbers: 10 World Trade HSS family 1.058 → 1.077.
- The converter's own classification is class 1 A, with total steel 1.0155. A grader rule of "family within 5%"
  would still flag HSS on such jobs. That is SDS2's own geometry, not a converter flaw.

## Runtime

The repair stage runs only for pieces that v5.5.3 rejects, and each unique piece is built once.
- Conversion wall time on BOX-C (load average 40-100): median 1.01x, total +2.2% over 18 jobs, range 0.86-1.34x.
  The worst cases are CLAYTON 7.245 (2,190 → 2,930 s) and IFC_19189 7.708 (987 → 1,313 s).
- The cost comes from pieces with many faces (W shapes with about 700 edges) that still fail after every repair
  combination.
- Diag (piece building only): median +15%.
- `brep.REPAIR_MAX_FACES` (5,000) bounds the stage.

## Reproduce (BOX-C)

- Scripts are staged at `s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-approx-pieces-7x/`;
  copies are in `job/`.
- Results are in `s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-approx-pieces-7x/`,
  under `diag/<run>/`, `holes9/`, `out/base553/` and `out/cand9/`.

| script | what |
|---|---|
| `mkvar553.sh NAME FILE:DEST…` | v5.5.3 tree with replaced decode files: `base553`, `cand8`, `cand9` (`cand9` = `patch/`) |
| `getjob3.py ID DEST`, `getjob4.py ID DEST` | Materialise a data-3 job from `jobs.json`, or from its `files/<fpc>.json.gz` manifest when `jobs.json` lacks it |
| `diag.py` (`diag2.py` = `diag.py.d9`) | Per-piece reject reasons and topology, and validation of repaired pieces |
| `holes_scan.py`, `marker_match.py` | Classify what stays open; check marker faces against the holes |
| `p1.py`, `p4.py`, `p5.py`, `p6.py` | Probes: unreadable piece files, negative weights, job_mtrl records, tube wall 2V/A |
| `conv.sh`, `conv_all.sh`, `convr.sh`, `conv_skip.sh`, `convd.sh` | `sds2_to_step.py --stage 2 --verify` drivers |
| `agg2.py`, `conv_cmp.py` | The tables in this README |
