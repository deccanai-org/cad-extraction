# IFC class-2 deep dive: `parts_outside_volume_tolerance`, `source_inventory_unavailable`, `not_read_back_large_file` (+ schema coverage)

Owner of the fix: **ifc_improver**. Everything here is read-only analysis plus patches; nothing in the kit, S3 or EC2 was touched.
Index analysed: `_state/conv/index.jsonl.gz` of 2026-10-01T21:11Z (IFC: 369 graded, class 2 = 172).
Kit baselines: snapshots in `patches/baseline/kit_1535_snapshot/` (the kit kept changing during the dive, see "Apply").

## TL;DR

| class-2 reason (models) | root cause | kind | fix (this dir) | evidence (real data-3 models) |
|---|---|---|---|---|
| `parts_outside_volume_tolerance` (25) | census expected volume wrong: HSS corner radii ignored (+2.1..+10.1 %), WT root fillets ignored (-4..-7 %), sloped-channel fillets/taper (+-2 %), `IfcArbitraryProfileDefWithVoids` unsupported, **openings (IfcRelVoidsElement) not subtracted** (bolt holes, copes, wall openings: ratios down to 0.42) | grader | census v3 (`patches/ifc_census.py`): exact areas for every standard profile (validated against the kernel's exact B-rep: ratio 1.00000 on 580 profiles), openings subtracted exactly (prism / box intersection in the host frame) or bounded as an interval `an_lo..an_hi`; join v3 checks intervals | 24 grader-caused models: 95 parts out (25 models with the census-v1 join) -> **0**; checked parts 20,056 -> **49,686**; 40 random other graded models: 446 -> 3,538 checked, 0 -> 0 out (no false positives) |
| same (1 of the 25: `1481043e`) | STEP writer prints reals with `"%.9g"`: a model placed 1456 km / 3036 km from the origin (SDS/2 state-plane coordinates) is quantised to 10 mm -> collapsed faces | **converter** | `ifc2step5.py` / guard / `db1/ifc2step5.py`: `_r()` = shortest round-trip `repr` (+0.5 % bytes) | 219 solids (39 invalid, 1 inside-out), coverage 0.61, 122/152 parts out -> **400 valid solids, coverage 1.0, 0/218 out** |
| (found on the way, hidden by the check) | transcode path writes faceted / surface bodies **without their openings** (copes, holes) | **converter** | `ifc2step5.py` (+guard, db1 copy) and the improver's `ifc2step6.py`: products with `HasOpenings` go to the kernel path | `0645b1a6`: 49 faceted beams/plates written uncut (kernel says the cuts remove up to 20.4 %); see section 1c |
| `source_inventory_unavailable` (16) | **mislabel**: the census was fine in all 16 (e.g. 89,094 expected = 89,094 STEP products); only the STEP-side part list was missing because STEP > RB_MAX (1 GB) -> `step_check --no-occ` writes no parts -> no join | grader | upstream already relabels to `per_part_verification_pending` (kit 15:35); the real fix is the chunked read-back below (it produces the part list) | 16/16 have `census.expected_parts` and `validate.products` |
| `not_read_back_large_file` (16, same models) | OCC read-back skipped for STEP 1.2-3.5 GB (memory) | grading strategy | `step_check_chunked.py`: bounded-memory OCC read-back of self-contained chunks (closure-complete), same per-part checks, retry, merged part list -> join + volume check; wired into ifc worker, grade worker and the new `final` pass (memory need = one RB_MAX read) | 163 MB STEP: chunked (8 x 20 MB) == full read-back on every total (2965 roots, 3211 solids, 612,359 faces, 3211 valid), peak RSS 0.56 GB vs 2.2 GB; 1.2 GB STEP (`085ebca9`): see section 2 |
| schema coverage | corpus: IFC2X3 3943, IFC2X2_FINAL 6, IFC4 2, CIS/2 2, all-zero 3, 0 ifcXML, 0 IFC4X3. Kit: IFC4X1 needlessly relabelled to IFC4X3_ADD2 (breaks alignment entities), IFC4 aliases (`IFC4_ADD2_TC1`...) not handled -> parse_error, ifcXML = guaranteed class 3 | converter | `fix_schema` relabels only what the kernel cannot load (`kernel_loads()` probe); `ifcxml2spf.py` (IFC2x3 + IFC4/4x3 ifcXML -> SPF) | real IFC4 ifcXML (buildingSMART conventions, 3,456 instances): 0 unresolved refs; IFC4 and IFC2x3 ifcXML walls -> STEP solid of exactly 3.0e9 mm3; IFC2X2 Tekla 16.1 relabel: 1309/1309 parts, 868 NetVolume checks all within 5 % |

Upstream status (kit at 15:35-15:45, other agents): census v2 already adds the HSS corner radii and WT root fillets and
**drops** the analytic value of any product with openings; grade_join pairs repeated names by sorted volumes and drops v1
HSS/T values. That alone takes the 24 grader-caused models to 0 outliers with 43,235 checked parts. What this dive adds on
top: openings are *computed* instead of dropped (+6,451 checked parts, +15 %; e.g. `043fe447` 69 -> 903, `0645b1a6`
66 -> 815, `0f8db82c` 1,726 -> 2,877), exact U / asymmetric-I / C / Z / rounded-rectangle / voids / derived profiles,
the two converter bugs, the chunked read-back, and the schema / ifcXML handling.

## 1. `parts_outside_volume_tolerance`

### 1a. Grader: the expected volume (census) was wrong - proof
* `tools/explain_parts.py` on the worst parts of every flagged model: the ratios cluster at fixed values per section
  (`0.9052`, `0.9309`, `0.9397`, `0.9436` = HSS sizes; `1.0541` = WT6x20; `0.93-0.94` plates / angle accessories with
  2-11 bolt-hole openings; Revit walls 0.63-0.85 and a slab 0.4165 with openings).
  * `1e7dc7a5` (11 KB, one part): `IfcRectangleHollowProfileDef(... 0.125, 0.291667, t=0.020833, Ri=0.020833, Ro=0.041667)`;
    sharp-corner area 2.25 in2 vs filleted 2.089 in2 -> expected ratio 0.928; measured 0.9263.
  * `0bb09346` plate SPD2-8: `IfcRectangleProfileDef` 0.5 x 0.4167 ft with 2 `IfcOpeningElement` holes (mapped polyline
    profiles, depth 0.0429 ft > plate 0.0417 ft).
  * `aa8a5888` (Revit 2022): frost walls with 1-2 openings -> 0.63-0.85.
* `tools/validate_profiles.py`: census area vs the ifcopenshell kernel's exact B-rep (OCC volume / depth) for 580
  profiles of 5 real files -> `evidence/profile_area_vs_kernel.txt`:

  | profile | census v1 | upstream v2 (15:35) | census v3 |
  |---|---|---|---|
  | RectangleHollow (67) | 1.0212 .. 1.1013 | 1.00000 | 1.00000 |
  | TShape (17) | 0.9333 .. 0.9578 | 1.00000 | 1.00000 |
  | UShape, sloped C/MC (65) | 0.9803 .. 1.0100 | 0.9803 .. 1.0100 | 1.00000 |
  | ArbitraryProfileDefWithVoids (19) | none | none | 1.00000 |
  | I, L, Rectangle, Circle(Hollow), ArbitraryClosed | 1.00000 | 1.00000 | 1.00000 |

  Kernel quirks found while validating (no data-3 impact, guarded in v3): an `IfcLShapeProfileDef` with `LegSlope`
  collapses to a triangle in ifcopenshell 0.9.0; IFC4 `IfcIShapeProfileDef.FlangeSlope` gives a malformed section ->
  census v3 claims no expectation for those (returns None).
* Openings in census v3 (`opening_bounds()`): host = the single `IfcExtrudedAreaSolid` (through <= 1 mapped item);
  each opening solid is mapped into the host frame (solid Position x profile Position); prisms along a host axis are
  intersected exactly (contained outline: area x overlap; axis-aligned rectangle in a box host: box-box), anything
  else contributes `[0, min(A, bbox-overlap) x overlap]`; duplicated cuts are de-duplicated, overlapping exact pieces
  fall back to `[max, sum]`; boolean / B-rep opening bodies -> no expectation. Tightness on the 24 models
  (`evidence/opening_expectation_tightness.txt`):
  * exact: 537 parts, STEP/net in **[0.9994, 1.0018]** (the same parts against the gross value: 0.627 .. 0.999)
  * interval: 350 parts, all inside, median width 0.16 %
  * no openings: 19,830 parts in [0.9847, 1.0025] (the low end = tessellated round bars, now inside the band)
* 3-way result on the same stored STEP part lists (`tools/rejoin3.py` -> `evidence/volume_check_3way_65_models.txt`):

  | set | A: census v1 + current join | B: upstream census v2 + join | C: census v3 + join v3 |
  |---|---|---|---|
  | 24 grader-caused models | 20,056 checked, 95 out (13 models) | 43,235 checked, 0 out | **49,686 checked (1,783 interval), 0 out** |
  | 40 random other graded models | 446 checked, 0 out | 3,502, 0 | 3,538, 0 |

### 1b. Converter: real-number precision (`1481043e`, `evidence/far_coordinates_1481043e.txt`)
All 394 products sit at x = -4.78e6 ft, y = 9.96e6 ft. `_r()` in `ifc2step5.py` formats `"%.9g"` -> `-1.45616136E9`
(10 mm steps). Local re-conversion with the kit converter vs the patched writer (ifcopenshell 0.9.0):
`roots 334 | solids 219 -> 400 | invalid 39 -> 0 | non-positive 1 -> 0 | coverage 0.61 -> 1.0 | 122/152 -> 0/218 parts out`.
Same function in `ifc2step5_guard.py` and `db1/ifc2step5.py` (identical file). The improver's `ifc2step6.py` already
writes coordinates with `'%.<prec>f'` (verified: 379 valid solids, 0/218 out on this model) - no change needed there.

### 1c. Converter: transcode ignores openings (`0645b1a6`, `evidence/transcode_openings_0645b1a6*.txt`)
`run_transcode()` (v5) and the transcode loop of `ifc2step6.py` never look at `HasOpenings`: a faceted / surface body
whose product has `IfcRelVoidsElement` openings is written uncut. `tools/faceted_openings.py`: 49 such products in
`0645b1a6` (SDS/2 v7.245: beams 911B2..., columns 353C1..., accessories w40223...); kernel volume with/without the cuts:
0.7957 .. 0.9997 (w40223 loses 20.4 %, p9391 3.4 %). They are surface models, so the volume check could never see it.
Patch: defer those products to the kernel path (`transcode_deferred_openings` stat). Re-conversion of `0645b1a6`:
transcode 2929 -> 2880 products, tess 815 -> 864, faces 577,285 -> 624,218 (+8 % bytes).
RESULTS_0645 (filled in below when the read-backs finished)

## 2. `source_inventory_unavailable` + `not_read_back_large_file` (the same 16 models)

| model | STEP GB | census expected | STEP products | app |
|---|---|---|---|---|
LARGE_TABLE

* Root cause: `worker.py` / grade `check_step()` run `step_check --no-occ` for STEP >= `RB_MAX` (1 GB): no per-part
  file -> `join` missing -> `classify_ifc` took the `source_inventory_unavailable` branch although the census is complete.
* Strategy: `patches/step_check_chunked.py` (new module, no change to `step_check.py`):
  1. one mmap/regex pass indexes every `#id=` (array, 8 bytes/entity) and the ends of `SHAPE_DEFINITION_REPRESENTATION`
     lines (product blocks of the ifc2step writers);
  2. chunks of ~`RB_CHUNK_MB` (150) are written as self-contained STEP files: header + transitive closure of every
     reference outside the chunk (contexts, units, shared DIRECTIONs - resolved through the index, so any writer and any
     split works) + the chunk's entities;
  3. the unchanged `step_check.py` runs on each chunk (`--jobs` in parallel, failed chunks retried alone), part rows
     merged (exact cross-chunk repeats dropped), totals summed, bbox united, markers from a whole-file text pass;
     assemblies (NAUO) are refused (text-only as before); no render (`render_ink` None, nothing blank-flagged).
* Equivalence (`evidence/chunked_readback_equivalence.txt`): `09f2c71c` 163 MB, full vs 8 x 20 MB chunks: identical
  roots / transferred / solids / shells / faces / checked / valid / invalid / nonpos / products; peak RSS 2.2 GB -> 0.56 GB.
* 1.2 GB `085ebca9` (23,608 parts): RESULTS_1200 (filled in below)
* Wiring (`patches/out/*worker.py.diff`): ifc worker and grade `check_step()` (also used by the new `final` pass) use
  the chunked read-back for STEP >= RB_MAX and for a read-back that is still OOM after the no-render retry; text-only only
  if the chunked run fails (`chunked_error` kept). grade `need_bytes` and the `final` fleet count `min(step, RB_MAX)`
  instead of 40-60x the whole STEP (a 3.5 GB STEP no longer needs a 210 GB box). Grade `redo`: results graded text-only
  are re-graded. `build_index`: `graded_by` gets `_chunked`, `weight_ratio` shows `checked_interval`.
* `patches/regrade_ifc.py`: census v3 + join v3 (and chunked read-back where it was text-only) for finished
  `ifc/results` without re-converting (local output by default; `--upload` only with fleet credentials).

## 3. Schema / format coverage (`evidence/schema_*.txt`)
* Survey of all 3,956 distinct IFC models (range GET of the header, zips opened): IFC2X3 3,943; IFC2X2_FINAL 6 (5 Revit
  exporter 16/18, 1 Tekla 16.1; all reused, grading pending); IFC4 2 (SolidWorks 2020, SDS/2 2020.04); CIS/2
  `STRUCTURAL_FRAME_SCHEMA` 2 (SDS/2 7.312 -> class 3 `source_cis2_not_ifc`); all-zero files 3 (source defect,
  verified byte by byte); 22 zip containers (15 .ifcZIP + 7 zips named .ifc, one with the member `ISO-10303-21.txt` -
  handled by the largest-member fallback); **0 ifcXML, 0 IFC4X3** in data-3.
* Kernel support (tested): 0.8.4.post1 loads IFC2X3 IFC4 IFC4X1 IFC4X2 IFC4X3 IFC4X3_TC1 IFC4X3_ADD1 IFC4X3_ADD2;
  0.9.0 (as installed here) IFC2X3 IFC4 IFC4X1 IFC4X3_ADD2; neither loads IFC2X2_FINAL / IFC2X_FINAL / IFC4_ADD2(_TC1) /
  IFC4X3_RCn / IFC2X3_TC1; both refuse ifcXML ("IFC-XML import temporarily disabled" / "not currently supported").
* Kit issues -> `ifc/worker.py` patch: IFC4X1 is no longer relabelled to IFC4X3_ADD2; IFC4X2/IFC4X3/TC1/ADD1 relabelled
  only if `kernel_loads()` says the kernel cannot load them; IFC4 aliases -> IFC4; ifcXML -> `ifcxml2spf.py` -> normal
  SPF path; `redo` re-opens `parse_error` results of those schema names and `ifcxml_unsupported` results.
* IFC2X2: the existing relabel works (Tekla 16.1 `83134afa`: 1309/1309 parts; re-converted in gid mode all 868
  NetVolume quantities within 5 %, median 1.000).
* `ifcxml2spf.py` (pure Python, schema-driven, conventions of IfcOpenShell's disabled `parse_ifcxml.cpp`): real IFC4
  ifcXML sample (CAFM-Connect, 3,456 instances, inverse containment) -> 0 unresolved refs, 0 warnings on both kernels;
  hand-made IFC4 and IFC2x3 ifcXML walls -> SPF -> `ifc2step5` -> 1 valid solid of 3.000e9 mm3 at the right placement.
  The improver's `ifc2step6` announces a built-in ifcXML reader: `work/xml/*.ifcxml` are ready-made regression inputs.

## Apply (ifc_improver)
The kit changed under this dive several times (census v2, sorted pairing, best-of, final pass, ifc2step6), so the edits
are delivered as a re-runnable generator: `python3 patches/make_patches.py` re-applies every edit to the current kit
files (anchored replacements, each must match exactly once) and writes `patches/out/<path>.diff` + `.patched` +
`REPORT.txt` (all edits applied at generation time, see REPORT). Order:
1. converter: `ifc/ifc2step5.py`, `ifc/ifc2step5_guard.py`, `db1/ifc2step5.py` (precision + openings), `ifc_v6/ifc2step6.py` (openings)
2. grader: `ifc_census.py` (whole file, census v3; all 4 copies), `grade_join.py` (5 copies), `coord/build_index.py`
3. read-back: add `step_check_chunked.py` (ifc/ and grade/), apply `ifc/worker.py`, `grade/worker.py`
4. schema: add `ifc/ifcxml2spf.py` (worker patch references it)
5. refresh: grade fleet re-grades text-only results (redo); census v3 for reused models through the `final` census jobs,
   for new conversions with `regrade_ifc.py` (or re-run); the coordinator's re-join picks up the new part lists.

## Risks
* Census v3 runs ~3x longer on opening-rich SDS/2 models (8 s -> 27 s for 6,543 parts / 4,705 openings; placement
  matrices memoised); interval expectations are bounds, never tighter than the truth (no false positive in 65 models).
* Chunked read-back: closure resolution assumes `#id=` starts a line (true for every writer seen); assemblies refused;
  memory = parent ~1 GB (index + one chunk's references) + one `step_check` per job (~2 GB per 150 MB chunk).
* Deferring faceted products with openings to the kernel: if the kernel cannot cut a surface model it writes it uncut -
  no worse than today; +8 % bytes on `0645b1a6`.
* `repr` reals: ~0.5 % larger files only when coordinates are large; identical text otherwise.

## Files
* `patches/make_patches.py`, `patches/out/` (diffs + patched copies + REPORT), `patches/ifc_census.py` (v3),
  `patches/step_check_chunked.py`, `patches/ifcxml2spf.py`, `patches/regrade_ifc.py`, `patches/baseline/` (kit snapshots)
* `tools/`: `explain_parts.py`, `validate_profiles.py`, `rejoin3.py`, `faceted_openings.py`, `faceted_openings_volume.py`, `schema_survey.py`
* `evidence/`: the text outputs quoted above; `work/`: inputs (result JSONs, part lists, small sources, test files)
