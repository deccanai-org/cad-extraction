# Classifier audit (z3conv grade/common/coord): class 1 false positives, class 2 false negatives, wrong class-3 reasons

Owner: classifier-audit deep-dive, 2026-10-01. Read-only on all kits; everything here is local (own venv, own work dir).

**Status:** the three patches below were picked up by the builder while this audit was still running. As of 15:45 local
the live `common/ifc_census.py`, `common|coord|grade|ifc|db1/grade_join.py` and `coord/build_index.py` contain every
hunk. The builder also added its own code around them (`final_jobs` census-v2 refresh, `per_part_verification_pending`,
`load_bytes`). The diffs in `patches/` are against the pre-patch snapshots (`orig_v3/ifc_census.py`,
`orig_v4/grade_join.py`, `orig_v4/build_index.py`) so the changes can be reviewed on their own.

## Findings (most severe first)

### F1. Class 1 included STEPs with parts that are not solids (grader bug + writer gap). 202 of 1,103 IFC class-1 models
* Rule: class 1 means "all solids valid". In `grade_join` a STEP part counts as present when it has faces, even with 0
  solids (`surface_parts`). `build_index` only wrote that to `issues_info`, so a model whose parts are all surfaces
  still got class 1. Nothing was checked on those parts: no validity, no volume.
* Latest index (21:58Z): **93 class-1 models have 0 solids** (100 % surface parts) and **109 more have some parts without
  a solid**. All 202 are SDS/2 IFC exports (`lists/ifc_class1_parts_without_solid.json`).
* Case 1, all surface: `ifc-015071d4bc56…` (BRIGHAM_JOB.ifc, reused Disk-1/2 STEP `f6d934f5…_14686165.stp`).
  * Source: 1,090 × `IFCSHELLBASEDSURFACEMODEL` whose boundaries are `IFCCLOSEDSHELL`.
  * STEP: 4,382 `SHELL_BASED_SURFACE_MODEL(OPEN_SHELL)`. Local `step_check` gives solids 0, shells 4,929, faces 80,743,
    exactly the fleet numbers.
  * Rewriting the same faces as `FACETED_BREP(CLOSED_SHELL)` (`tools/sbsm_to_brep.py`) gives **4,924 solids, 4,924 valid,
    0 non-positive volume**. So the source holds closed solids, and the STEP turned them into surfaces.
  * `ifc2step5.item_to_step` writes every SBSM boundary as `OPEN_SHELL`. `ifc_v6/ifc2step6.py` already has a
    `closed_surface` role for this case. Re-converting the 93 with v6 instead of reusing them should make them solid.
* Case 2, partial: `ifc-1f5385862671…` (RIPPLING WOODS). 177 `FACETED_BREP(CLOSED_SHELL)` parts, of which 34 read back
  as a shell with no solid. `tools/free_edges.py` finds **28 free edges on each of the 34**, so the "closed" shells are
  open (not watertight). New ifc2step5 conversions have the same defect (10 of the 109, e.g. `33cc1bcf…` part `VB_3`:
  17 shells / 67 faces).
* Fix (live): `parts_without_solid:N` is now an **issue** (class 2) for IFC and DB1, with an `explain()` entry. This is
  also needed for v6: its L3/L4 fallbacks write failing solids as surface models, which would otherwise be class 1.

### F2. Class 2 false negatives: census volume formula artefacts. 111 class-2 models had no other defect
`ifc_census` computed the expected `an` volume as profile area × depth. Three errors in that:
1. **Hollow rectangles (HSS):** corner radii were ignored. Predicted vs observed ratio: HSS2x2x1/4 0.908 vs 0.9052,
   HSS2x2x3/16 0.9334 vs 0.931, HSS6x6x1/2 0.9415 vs 0.9397 (`tools/diag_volume_outliers.py`).
2. **T sections (WT):** the root fillets were ignored. WT7x11: predicted 1.0715, observed 1.0736.
3. **Openings (`IfcRelVoidsElement`, i.e. bolt holes and copes):** they were not subtracted. Examples: plate `10081M1`
   with 12 openings, ratio 0.88; angles `a178` with 11 openings, 0.928; walls with doors, 0.63; slab with an opening, 0.4165.
* Scope: all **315** class-2 models flagged `parts_outside_volume_tolerance` (4.4 GB of sources) were re-run locally.
  Fleet census + current join is compared with the patched census + patched join, both on the fleet STEP parts:
  * Control: the local original census reproduces the fleet joins for 315 / 315 (0 mismatches).
  * Models with any outlier go from 313 to **32**. Per-part volumes checked go from 226,394 to 419,729.
  * **111 / 111 models whose only class-2 signal was the volume flag now have 0 outliers.** Under the new F1 rule each
    one becomes class 1 unless it has surface parts.
  * The 32 left are real: fasteners at 3.5-86×, walls at 57×, `1481043e986c` plates at −0.23 / 2.05. All 32 also carry
    other class-2 signals (`lists/ifc_volume_flag_before_after.json`).
* An earlier 25-model sample matches: 24 / 25 go to 0. The one left (`1481043e986c`) is a genuine defect and keeps its flag.
* Fix (live): census v2 handles HSS radii and T root fillets, drops `an` (and gross quantities) when the part has
  openings, and writes `cv: 2` on every part. Fillet terms for U / L / Z / I-edge were tried and **reverted**: on sloped
  channels (C3x6, FlangeSlope 9.5°) they created false outliers at 0.9496.

### F3. The volume check never ran on 81 % of class-1 models (name mode used unique names only)
* 891 of 1,103 class-1 models had `weight_ratio.checked == 0`. In name mode (old writers) only parts with a unique name
  were paired, and SDS/2 piecemarks and Tekla `BEAM` / `PLATE` names repeat.
* Fix (live): for a census-v2 inventory, each repeated name pairs its expected volumes and its STEP volumes in sorted
  order (optimal 1-D assignment). This only happens when every source part of that name was matched and no STEP part of
  that name is left over.
* Tested on the 40 class-1 models that have expected volumes: checked parts go from 1,229 to **12,727** (models with a
  check from 29 to 36), with **0 outliers**. So it demotes nobody.
* For v1 (old) census records, grouped pairing stays off and `an` is ignored for RectangleHollow / T. A rejoin from
  stored detail therefore cannot create new outliers before the census v2 refresh has run.

### F4. Curved profiles were exempt from any volume check
* With `curved_volume_counts: False`, a Circle / CircleHollow part could be at any ratio and still pass.
* Measured tessellation loss is 0.958 to 1.021 (12,580 curved parts, 62 models). Parts outside the band
  **[0.90, 1.05]** are now counted (`outside_curved_gross`). On current data that adds 0 flags.

### F5. Latent: coverage rounding
`round(m/e, 4)` turns 1 missing part in more than 20,000 into 1.0. Coverage is now rounded **down**
(`grade_join.cov4`). There are no current cases.

### F6. SDS/2 class-3 "source" reasons were wrong for most jobs (imported reference models, not empty sources)
The type of each job's member was read from `mem/mem_idx` (ranged GET of the first 600 KB) and checked against the
file manifest:
* **v4 results** (first index):
  * All 50 `source_no_buildable_pieces` jobs are a single **`DWF Import`** member. 30 of them skipped 2 to 44,251
    "DWF Imported" pieces. The other 20 enumerated nothing at all; one of those, HHH, has a 484 MB `mem/1` and 32,490
    piece files.
  * 3 of the 21 `source_no_members` are DWF too. 5 of the 6 `zerodivisionerror` failures are DWF jobs crashing in
    `plate_local_area`.
  * A DWF piece record (`subm/100`, 7,400 B) holds big-endian coordinate triplets (22123.5, −132.0, −218.4, …), so the
    geometry is there.
* **v5 results** (latest index): 130 class-3 jobs are labelled `source_no_members`.
  * 110 are `DWF Import` jobs, holding 1,623,861 placed piece files and 19.7 GB of piece data.
  * 1 is a 7.619 `REFERENCE MODEL` job.
  * Only **19 are really empty**: zero-filled `mem_idx` and no `mem/<n>` files. 4 of these have orphan piece files,
    e.g. BH1 with 17,238.
  * See `lists/sds2_v5_no_members_audit.json`.
* The SDS2 fixer's v5.1 builds these as corpus R and writes `empty_job_proof`. The v5 failures are **not** re-run
  automatically (`redo_labels: ["v4"]`). **`lists/sds2_v51_redo_ids.json` holds the 111 job ids for a targeted v5.1
  re-run.**
* Fix (live): when there is no `empty_job_proof`, the labels say emptiness is unproven:
  `no_member_records_read (…NOT proven…)` and `converter_wrote_nothing (…)`. `explain()` now files them under
  converter_feature instead of "source data absent, nothing to convert".

### F7. Latent: a failed re-grade became class 3 `step_read_failed`
When a grade result had status ≠ ok, the code fell through with `validate = {}`, and `step_checks` then added
`step_read_failed`. Now `grading_failed()` returns the row ungraded (class None). Only `reused_step_missing` is class 3,
with its own reason. There are no current cases (all 1,539 grades are ok).

### Checked and found sound (no change needed)
* **Units:** across all 195 first-index class-1 models, the median smallest part dimension per model is 3.2 to 229 mm and
  the median length 140 mm to 3 m. Every model with volume pairs has a median ratio of about 1.000. No unit errors.
* **Stray parts / bbox:** the ratio of full to 1 %-trimmed extent is ≤ 1.9 except for 2 sparse models with 6-7 parts.
  The near-empty renders (ink < 0.002) are sparse embed-plate models; the render was looked at and is not a defect.
* **Non-physical exclusion:** census skips openings, spaces, grids, annotations and virtual elements. Every part listed
  as missing in the 54 IFC models with coverage < 1 is physical (beams, proxies, members, doors…).
* **SDS2 class 2 / DB1:** no class-2 model there should be class 1. Their blockers are real stand-ins (joist envelopes,
  nominal bolts, bolt groups). `799ba840b7` (1 W10x12, `steel_ratio` 1.059) is a real 5.9 % weight difference: the
  ratio comes from `ratio {:.3f}`, not from rounded tonnes.
* **`step_check` reproducibility:** the unmodified kit `step_check.py` was run through an OCC→OCP shim on OCP 8.0.1, the
  same OCCT the fleet uses. It reproduces the fleet read-back exactly (solids, shells, faces, bbox, render ink).

## Before / after on all current results (offline simulation, `work/sim_full.json`)
Setup:
* Both `build_index` versions (pre-patch `orig_v4` and `patched`, each with its own `grade_join`) were run over local
  copies of `scan/contents_*`, the 1,067 IFC / 55 DB1 / 168 SDS2 results and the 1,539 grade results.
* Reused IFC / DB1 grades were rejoined locally (1,481), the same way `rejoin_grades` does it.
* The 355 models re-censused locally use census v2; the rest keep their v1 inventory.

| | before | after |
|---|---|---|
| IFC class 1 | 1,127 | 1,005 |
| IFC class 2 | 1,453 | 1,575 |
| IFC 1 → 2 | | 211: `parts_without_solid` 209; `coverage_by_part_count_only` 2 (two Revit models, 1,672 = 1,672 by count only) |
| IFC 2 → 1 | | 89, all from removing the census volume artefact |
| new `parts_outside_volume_tolerance` / curved flags | | **0** (grouped pairing and curved band demote nobody) |
| SDS2 class 3 | 151 | 151; 134 relabelled from `source_no_members` / `source_no_buildable_pieces` to the "unproven" labels |
| DB1 | unchanged | unchanged |

Expected end state, once the open items below are done:
* The 209 surface-part models come back to class 1 only if their re-conversion gives real solids. ifc2step6 does that
  for closed shells; Brigham showed 4,924 / 4,924 valid.
* Up to 111 SDS2 jobs move from class 3 to corpus R class 1 / 2 after the v5.1 re-run.
* The census-v2 refresh promotes the rest of the volume-artefact models: 87 of the 111 volume-only models have no
  surface parts (`lists/ifc_volonly_outcome.json`).

## Open items for the builder / other owners
1. **IFC converter owner:** re-convert the 93 + 109 SDS/2-IFC models in `lists/ifc_class1_parts_without_solid.json`
   with ifc2step6. `build_index` already lets a new conversion supersede a reused STEP.
2. **SDS2 owner:** run v5.1 on `lists/sds2_v51_redo_ids.json` (111 ids).
3. **Census v2 refresh:** `final_jobs` (live) re-censuses only models tagged `parts_outside_volume_tolerance`. That covers
   all 315. Start with `lists/ifc_recensus_priority_ids.json`: 111 models that should become class 1 once they have no
   surface parts.
4. **`count`-mode joins** (names that did not survive an old writer) no longer reach class 1
   (`coverage_by_part_count_only`): a part count proves neither identity nor volume. There are no current cases.
5. **Name mode** matches by name only and never cross-checks the category. That is acceptable for coverage, but a STEP
   with the right names and swapped geometry would pass when no expected volumes exist. That is the case for 891
   class-1 models with v1 census until the v2 refresh, and for any SDS/2 IFC whose bodies are B-rep.

## Reproduce
* Python: `venv/` (python 3.12, cadquery-ocp 8.0.1 = OCCT 8.0.1, ifcopenshell 0.9.0, the fleet census kernel).
* `tools/occshim/` maps the `OCC.Core` imports of the kit `step_check.py` to OCP. `tools/step_check_ocp.py` is a copy of
  `step_check.py` that differs only in the bbox getter and the root→PRODUCT mapping, because `InterfaceModel.Number()`
  returns 0 in OCP 8.
* `tools/grouped_volume_check.py`, `tools/diag_volume_outliers.py`, `tools/rejoin_compare.py` (before/after join),
  `tools/fetch_and_census.py` (original vs patched census on downloaded sources), `tools/free_edges.py`,
  `tools/sbsm_to_brep.py`, `tools/simulate_index.py` (both `build_index` versions on local copies of all results).
* Raw evidence is in `work/`: `vol_v2_before_after.json`, `c1_before_after_volume.jsonl`, `before_after_volume.jsonl`,
  `sds2_v5_nomem.json`, `sds2_class3_member_types.json`, `stp/brigham*.check.json`, `sim_full.json`.
