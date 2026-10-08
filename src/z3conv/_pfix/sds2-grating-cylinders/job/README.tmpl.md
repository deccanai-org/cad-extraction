# sds2-grating-cylinders: SDS2 converter patch (bar grating + exact rods / anchors)

Fixes two class-2 flaws of the SDS2 pipeline from data SDS2 itself stores. Nothing is placed by rule, no open mesh
is closed with new faces, and anything not validated against SDS2's own piece weight stays tagged `[approx: ...]`.

* **`sds2 grating geometry`** (126 class-2 models live): bar grating panels and grating treads (`GR...` / `GT...`
  pieces) were written as a solid panel, 5-10x SDS2's weight. v4 tagged it `grating_solid_panel`; v5.x falls into
  `plate_from_vertices`. With this patch the converter builds the grating SDS2 modelled: bearing bars, bands, carrier
  plates and nosing from the piece's faces, plus every cross bar. It is written exact (untagged) only when its weight
  is SDS2's piece weight (+-3 %), or when it is a panel cut from its stock (see below).
* **`sds2 mesh_cylinder`** (570 class-2 models live, 203,332 placements): rods, studs and anchors whose rings are
  not on a piece-local coordinate axis were written as a straight rod *guessed* along the mesh's longest extent.
  * Straight rods now get exact cylinders on the axis of the piece's own end caps.
  * Bent / hooked rods now get the piece's own faceted B-rep. This is the SDS2 fixer's "hooked-anchor B-rep first"
    draft, plus merging of bend-facet vertices that miss each other by up to 0.002 in.

Bases and patch files (all unified diffs, `patch -p1` from the folder that contains `sds2-step-pipeline/`):

| file | base | notes |
|---|---|---|
| `sds2-grating-cylinders.v5.5.3.patch` | `sds2-step-pipeline-v5.5.3.zip` (sha256 `706e1289...c0a9`, current release) | **use this one** |
| `sds2-grating-cylinders.patch` (= `.v5.4.patch`) | `sds2-step-pipeline-v5.4.zip` (sha256 `bf4a07fc...f2906`, the base named in the task) | same change, plus the `_absurd()` tuple fix at the call site (v5.5.1 fixed it inside `_absurd`, so the 5.5.3 patch leaves it out) |
| `sds2-grating-cylinders.on-v5work.patch` | the SDS2 fixer's `v5work` draft tree | extends the fixer's hooked-anchor draft in place |
| `merge-with-sds2-weights-failures.v5.5.3.patch` | v5.5.3 + `sds2-weights-failures-v5.5.3.patch` | optional: the one hunk that conflicts with that patch, resolved (see Overlaps) |

Folder: `work553/` and `work/` are the patched v5.5.3 / v5.4 trees, and `base553/` and `base/` the untouched bases.
`data/` holds the measurements (`gr4f` grating per piece, `rod2` rod replay, `plan1` cut-panel probe, `tube1_probe`
round tubes, `conv` conversion comparisons). `job/` holds every script that ran on BOX-C, and `img/` the renders.

**S3 status.** Interim patch files and README were uploaded to
`s3://annotationprod/cad-disk-extract/_control/z3conv/sds2/pfix/sds2-grating-cylinders/` at 2026-10-02 04:26Z. Those
interim patches lack only the `SDS2_GRATING_BUDGET_S=0` switch (`>=` instead of `>`); everything else is the final
code. The final files in this folder could not be uploaded because the `annotationprod-publish` SSO session expired.
To upload them: `AWS_PROFILE=annotationprod-publish aws s3 cp --recursive . <that prefix> --exclude "*"
--include "*.patch" --include README.md`.

The patch touches `decode/to_step2.py` and `decode/manifest.py`, and adds `decode/grating.py`. The CLI and output
files are unchanged. The manifest gains `grating` and `rods` sections.

All compute ran on BOX-C (i-0d97427e58ca5ef28), under `/work/agentwork/sds2-grating-cylinders`. Results are at
`s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-grating-cylinders/`
(`conv/<ver>/<job>/`, `gr4f/`, `rod2/`, `tube1/`, `plan1/`).

## What SDS2 stores (decoded on real jobs)

### Grating (`GR` panels, `GT` treads; checked on 7.312 / 7.323 / 7.331 / 7.425 / 7.613 / 8.004)
* **Piece-file B-rep.** The bearing bars and end bands are stored as faces.
  * On panels they sew into one closed solid. Example: SLC4 GR1 3/4x35 13/16, one 194-face body.
  * On treads, the bars and nosing are open tubes. Their end outlines lie on the carrier plates' faces, so those
    edges have 3 users and the piece does not sew. This is why v4 / v5 fell back to a panel.
* **Cross bars.** Each cross bar is stored as one flat rectangle on the walking face: 0.001 in below the face on
  panels, 0.005 in above it on treads. It is exactly as wide as the cross bar and sits at the cross-bar pitch. It is
  a zero-thickness marker, not a solid.
* **Piece-table record.** The slot holds 8 grating numbers: bearing-bar thickness, bar depth, bar spacing, cross-bar
  width, cross-bar depth, cross-bar spacing, panel width, panel length.
  * Stored as f64 at +0x168 in 852 / 902-B slots and at +0x158 in 8.0 slots. Located by value
    (`grating.slot_fields`: the depth must equal the bars' depth in the B-rep, the cross-bar width the stored
    rectangles' width).
  * Example: SLC4 7.331 GR1 3/4x35 13/16 = `0.1875, 1.75, 1.1875, 0.1875, 0.1875, 4.0, 35.8125, 97.5`.
* **SDS2's piece weight is exactly that union.** The union is the closed bars + bands, plus the cross-bar rectangles
  extruded by the record's cross-bar depth. Examples: SLC4 GR1 3/4x23 15/16 x 97 1/2, 199.0 lb built vs 199.0 lb
  SDS2; SHERIFFS GR3/4x23 9/16, 22.03 vs 22.06 lb. Uncut panels come out at 1.0001.
* **A panel cut down in SDS2 keeps the uncut panel's weight** (strip, notch, opening). It is weighed for its full
  W x L stock. Example: TEMP Wayne Farms GR1 1/4x36 cut to 11 1/2 in, built / SDS2 = 0.322 = 11.5 / 36.
  * Validation: the piece's weight per plan area must be the stock's. Built / SDS2 weight is compared with plan area /
    (W x L), where the plan area is the union of the stored up-facing faces, with the gaps between bars closed.
  * Over the 115 cut pieces of the test jobs, the quotient is 0.94-1.20 (`data/plan1/`). Narrow strips sit at the top
    end because they carry relatively more band.
  * A piece that lost bars would come out low, and one that closed voids would come out high.
* **Deep cross bars.** Some products record cross bars deeper than the bearing bars: 1504 EQUADOR GR3/16 (0.5 in
  under a 0.197 in plank), and the DSCC mesh panels.
  * SDS2's weight confirms the literal reading: 1.012-1.013. Clamping the cross bars to the plank depth gave 0.476.
  * These pieces must match SDS2's weight; no cut-panel exemption applies to them.

### Rods, studs, anchors (TURNED names: RB, RD, WS, TWS, THD STUD, DBA, AB ...)
* `turned_local` only finds rings on a piece-local *coordinate* axis through the *origin*. The rods it misses are of
  these kinds:
  * **Straight N-gon prisms whose axis is diagonal or offset.** Examples: DSCC joist web rods RB3/4 at 45 deg in their
    local frame; TEMP JOB RGK RB1/8. The two end caps give the axis. Every vertex lies on the circle of the named
    diameter: vertex radius / name diameter = 1.000 on all 26,815 placements.
  * **Bent / hooked rods** (multi-segment ring sweeps) whose B-rep closes.
  * **Bent rods with 0.0015 in sliver gaps** between bend facets (SUSQUEHANNOCK / RIPPLING RB1/4).
  * **Studs with a duplicated end cap** (TWS, THD STUD).

## Changes

`decode/grating.py` (new), `build(V, F, wt, record)`:
* **Bodies:**
  * Closed bodies are taken as stored.
  * An open bar / nosing tube is closed at its own stored end outlines, but only if every outline lies inside a
    stored face of another body. That end face is a contact face that disappears in the union.
  * Otherwise the piece is split into the closed cells bounded by the stored faces (OCC `BOPAlgo_MakerVolume`), for
    non-manifold treads of up to 300 faces.
* **Cross bars:** each stored rectangle, put on the walking face and extruded by the record's cross-bar depth.
* **Fuse:** everything is fused into one solid. Coplanar faces are deliberately **not** unified.
  * `ShapeUpgrade_UnifySameDomain` would merge the walking surface into one face with a hole per opening (OLT
    GT1/8x34 5/8: 392 inner wires).
  * `BRepCheck` time is quadratic in a face's wires, and the `--verify` read-back checks every placement. Per placed
    grating that is 3.0 s instead of 0.9 s (SLC4 GR1 3/4x35 13/16: 4.8 s vs 1.7 s), at 2.4x the faces
    (`job/gtime3.py`).
  * The v5.4-based pre-final build (`conv/v55/`) still unified faces. Its One Light Tower read-back (2,038 grating
    placements) was still running after 2.3 h when it was stopped.
* **Accepted when:**
  * the built weight is within 3 % of SDS2's; or
  * it is a cut panel: lighter than SDS2's weight, inside the record's W x L stock, cross bars stored, and weight per
    plan area 0.93-1.25x the stock's (`CUT_DENSITY`); deep-cross-bar pieces excluded.
* **Otherwise:** returns `None` with a reason, and the caller keeps the tagged panel.

`decode/to_step2.py`:
* **Grating hook.** `GR` / `GT` pieces go through `grating_placed()` before the exact-B-rep branch. The build is cached
  per piece (shared part + placement).
  * Built gratings are exact parts (`builder exact_brep`, no tag). They stay out of the steel tally like before.
  * Failures fall through to the old path. The panel stand-in now reads "bar grating as its panel outline (bars not
    built: <reason>)", so it is typed `grating_solid_panel` with its `needed` text instead of `plate_from_vertices`.
  * Time budget per job: `SDS2_GRATING_BUDGET_S` (default 1800 s; 0 turns the builder off). Gratings left after it
    keep the tagged panel.
* **Rods (`special_solid`).** After the two `turned_local` attempts, `turned_any_axis()` reads the rings along the
  common normal of the piece's planar end caps (duplicate caps dropped) and writes exact cylinders. Accepted only when:
  * every face vertex is on a ring;
  * the shank diameter is the name's (`RB1/2` -> 0.5 in, `_name_dia`);
  * the cylinders weigh 0.75-1.33x SDS2's weight.
* **Bent / hooked rods.** When `special_solid` still has to guess, the piece's own B-rep is used:
  * `brep_placed()` (the fixer's draft), else `rod_brep_placed()`;
  * `rod_brep_placed()` merges vertices within 0.002 in, then sews as `brep.solid` does, with the same 0.6-1.6 weight
    rule as `brep_placed`.
  * The straight-rod guess remains only when neither closes.
* **v5.4 patch only:** `_absurd(sh[1] if isinstance(sh, tuple) else sh)`. v5.4 dropped every special-path piece whose
  exact B-rep was a shared tuple (`absurd_extent_corrupt_source_geometry`). v5.5.1 fixed this inside `_absurd`.
* **Manifest.** New `grating` and `rods` sections:
  * `grating`: pieces built / cut / tread cells / cross bars / not built by reason;
  * `rods`: cap-axis cylinders, bent B-reps, remaining straight guesses.

`decode/manifest.py` copies those two sections into the manifest and gives `NEEDED["grating_solid_panel"]` a precise
text.

## Before / after on real jobs

### 1. Grating builder, every grating piece of 12 fetched jobs (final code, `data/gr4f/`)
__T1__

### 2. Rod chain replay, every TURNED piece of 27 fetched jobs (`data/rod2/`, placements)
| outcome | v5.4 | patched |
|---|---:|---:|
| rings on a local axis (`turned_local`, unchanged) | 66,908 | 66,908 |
| **straight-rod guess** (`mesh_cylinder` stand-in) | **30,708** | **0** |
| exact cylinders on the end-cap axis | - | 26,815 |
| exact B-rep, bent / hooked (fixer draft) | - | 2,137 |
| exact B-rep after 0.002 in vertex merge (SUSQUEHANNOCK 1,369, RIPPLING 350, SLC4 37) | - | 1,756 |
| B-rep built but dropped by the v5.4 tuple bug (fixed in v5.5.1 too) | 2,543 | 0 |
| no geometry | 1 | 1 |

Largest jobs, guessed rods -> patched:

| job | guessed rods | patched |
|---|---:|---|
| TEMP JOB RGK 8.004 | 21,038 | 20,013 cylinders + 1,025 B-rep |
| VALLEY GROVE 7.331 | 3,345 | 3,134 + 211 |
| THERMOFISHER 7.708 | 1,637 | 1,582 + 55 |
| SUSQUEHANNOCK 7.619 | 1,573 | 204 + 1,369 (merged B-rep) |
| CLAYTON 7.245 | 1,156 | 1,156 + 0 |
| DSCC 7.312 | 178 | 45 + 133 |
| SHERIFFS 7.425 | 61 | 46 + 15 |

On the straight cylinders: cylinder weight / SDS2 weight is 1.0001-1.008, and diameter / name diameter is 1.000.

### 3. Full conversions, v5.4 vs v5.4 + patch (`sds2_to_step.py --stage 2 --verify`, same jobs, same box)
__T3__

### 4. Full conversions, v5.5.3 vs v5.5.3 + patch (final code)
__T4__

**Cost of real grating geometry (read-back and file size).** A grating is one exact solid of 750-5,500 planar faces.
* `--verify` runs `BRepCheck_Analyzer` on every placed solid. After a STEP round trip that is 0.4-2.5 s per grating
  placement on BOX-C (`job/gtime5.py`, `job/gtime7.py`). One Light Tower, the class-2 maximum with 2,038 grating
  placements (the next model has 1,079):
  * total wall 1,043 s -> 5,640 s on the loaded BOX-C (load 60-100 on 64 vCPU);
  * STEP 175 -> 406 MB.
* The fleet timeout is 14,400 s (`worker.py`, `SDS2_TIMEOUT_S`).
* Other grating jobs: +3-35 % wall and +1-45 % STEP.
* Alternatives measured and rejected:
  * unified faces: 2.4x fewer faces, but 3x slower `BRepCheck`, quadratic in the walking face's holes;
  * a compound of non-overlapping solids: 30 % smaller and 35 % faster to check, but each grating would read back as
    400-900 "placed solids" and distort the read-back counts.
* `SDS2_GRATING_BUDGET_S=0` turns the grating builder off (gratings keep the tagged panel).
* Suggestion for the pipeline owner (not part of this patch): cache `BRepCheck` validity per shared part in
  `verify_step.py`. A rigid placement keeps validity, and One Light Tower holds 28 unique grating parts against
  2,038 placements.

Images (`img/`; the right panel is v5.4 + this patch, labelled "v5.5" from before the rename):
* `sheriffs_grating.png`: GR3/4x23 9/16, 120.3 lb panel -> 22.1 lb grating (SDS2 22.1).
* `psu_tread.png`: GT1x12 1/8 tread, 413.5 lb -> 38.7 lb (SDS2 39.1).
* `olt_tread.png`: One Light Tower GT1/8x34 5/8.
* `dscc_rod.png`: RB3/4 joist web rod. v5.4 guessed it along local y; it really lies on its diagonal cap axis.

## Corpus impact (live data, `class_2_partial.jsonl.gz` 2026-10-02T02:51Z)
| flaw key | class-2 models | stand-in placements | models where it is the only flaw |
|---|---:|---:|---:|
| `converter_feature \| sds2 grating geometry` | 126 | 11,100 | 0 |
| grating stand-ins of any type (`GR` / `GT` real types, incl. `plate_from_vertices` counted under `sds2 approx pieces 7.x`) | 377 | 31,088 | - |
| `converter_feature \| sds2 mesh_cylinder` | 570 | 203,332 | 0 |
| both | 21 | | |

* **Models touched:** 736 class-2 models carry grating or `mesh_cylinder` stand-ins. In 27 of them the gratings and
  rods are the only approximate pieces, so their `sds2 approx pieces 7.x` key would clear too.
* **Class-1 lift from this patch alone: 0 models.**
  * Every one of the 675 models with the two flaw keys has at least one other flaw. The most common are: bolt
    records absent (566), concrete shapes (439), holes derived from bolts (436), undetailed members (431), family
    weight (391), mating holes not stored (360), and joist vendor design (350).
  * Only 2 models have exactly one other flaw: concrete shapes, and sds2 pieces not built.
  * Even counting a `family weight` flag on rod families only (RB / WS / ROUND ...) as fixed, the lift stays 0.
* **What the patch removes once the models are re-converted with it:**
  * the `mesh_cylinder` stand-in, in the 27 replayed jobs: 30,708 -> 0 straight-rod guesses;
  * the grating panel stand-in: 3,768 of 3,782 grating placements built exact in the 12 grating jobs.
  * Both flaw keys should drop out of nearly all 675 models.
  * The remaining grating panels are tagged with the exact reason (no faces in the piece file, weight mismatch).
* **Steel ratio.** Gratings stay out of the steel ratio, as before. Exact rods replace guesses of the same diameter,
  so `weight_check.ratio` moves by 0.0001-0.0015 on the test jobs.

## Not fixed / left as is
* **Grating pieces whose file has no faces.** PSU 8.004 has 22 pieces of 261 B (7 placements); PNW has 4 pieces with
  no piece file (unplaced). They keep the old behaviour. Bars could only be laid out by inferring SDS2's layout rule,
  which is not stored.
* **Weight checks that fail; these stay tagged panels, with the reason in the name and in the manifest.** Over the 12
  jobs that is 14 of 3,782 grating placements (7 of them are PSU's pieces without faces, above):
  * DSCC: GR1/8x16 1/8 mesh panels (2 placements) at 0.947x, deep cross bars;
  * DSCC: 12 unplaced pieces at 1.03-1.06x, plus 1 unplaced tread whose faces bound no cells;
  * 1504 EQUADOR: 3 unplaced pieces at 1.03-1.05x;
  * FMI 7.132: GR1 1/2x101 1/8 (2 placements) at 3.78x and GR1 1/2x77 3/8 (1 placement) at 31.4x SDS2's weight;
  * FMI 7.132: 2 pieces with no SDS2 weight (1 placement each);
  * 3 unplaced pieces with no cross bars stored (PSU 1, Wayne Farms 2).
* **Round HSS / pipe** (`data/tube1_probe/`, 27 jobs). Exact wherever their faceted B-rep closes: 18,696 placements.
  Of the 717 placements whose B-rep does not close:
  * 441 are bent or coped (more than 2 ring stations): open meshes, not closed here;
  * 245 have no readable face topology;
  * 9 are not two rings;
  * 22 are plain straight tubes, and none of them can be validated except one:
    * 15 weigh 1.99-2.01x SDS2's recorded weight. Example: THERMOFISHER PIPE 1 1/4 STD x 183.4 in, 34.8 lb from the
      stored rings, while SDS2 records 17.4 lb.
    * 5 have a corrupt SDS2 weight (1e305 lb) and 1 has none.
    * 1 fits (SOCORRO).
  * A plain-tube builder was written and probed (`data/tube1_probe/round_tube_probe_code.diff`) but is **not** in the
    patch: it would make 1 placement exact.
* **Rods with no B-rep and no rings:** 1 placement (UOM Union). Unchanged.
* **Models converted earlier.** 102 of the 126 grating models carry reused pre-v5 results (`converter_code` null).
  Like all other models, they improve only when the fleet re-converts them with this patch.

## Overlaps with other patches (checked with `patch`, both orders, on v5.4 and v5.5.3)
* **sds2-pieces-not-built, sds2-approx-pieces-7x:** apply cleanly with this patch in both orders.
* **sds2-weights-failures:** exactly one hunk conflicts. Its `turned_brep()` and this patch's guessed-rod -> B-rep block
  are inserted at the same line, right after `builder = "special_primitive"`. Both implement the fixer's draft.
  * `merge-with-sds2-weights-failures.v5.5.3.patch` is the resolution, applied on top of
    `sds2-weights-failures-v5.5.3.patch`. It keeps `turned_brep()`, then adds `rod_brep_placed()` only where the
    stored B-rep does not close as stored, so `turned_brep()` keeps its weight rule for closed B-reps.
  * `turned_brep()`'s 15 % weight rule alone would leave the 1,719 SUSQUEHANNOCK / RIPPLING RB1/4 rods as guesses:
    their B-rep is 1.57x SDS2's weight, and even the straight guess is 1.47x. `brep_placed`'s own 0.6-1.6 rule
    accepts them.
* **SDS2 fixer `v5work`:** `sds2-grating-cylinders.on-v5work.patch` extends its hooked-anchor draft in place.
  `brep.loops_of` and `slot_size_job` are untouched.

## Reproduce
* Conversions: `job/conv.sh <ver> <job>` (`--stage 2 --verify`, timeout 6 h). The queue is set up in
  `job/requeue.sh`: `gate3.sh` launches at most one job per 2 min, and only while fewer than 14 of this job's python
  processes run.
* Version labels:
  * `base54` = v5.4; `v55` = v5.4 + the pre-final patch (same geometry, but it still unified faces and lacks the
    cut-panel density check);
  * `v553` = v5.5.3; `v553h` = v5.5.3 + the final patch; `v54h` = v5.4 + the final patch.
* Manifest comparison: `job/cmp.py`. BRepCheck timing: `job/gtime3.py`.
* Grating table per piece: `job/gr4.py`. Plan-area probe: `job/plan1.py`.
* Rod replay: `job/rod2.py`. Round-tube probe: `job/tube1.py`. Images: `job/render.py`.
* Jobs are fetched with `job/getjobs.py` from the data-3 `jobs.json`.
