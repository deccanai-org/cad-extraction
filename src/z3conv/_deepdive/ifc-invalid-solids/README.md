# IFC class-2 reason `invalid_solids` - deep dive (z3, 2026-10-01)

Owner of the fix: **ifc_improver**. Everything here is local; nothing was uploaded or edited outside this directory.

## 1. What the category is

`coord/build_index.py: step_checks()` adds issue `invalid_solids:N` when `step_check.py` (OCC 8.0.1 `STEPControl_Reader`,
default shape healing on transfer, then `BRepCheck_Analyzer(solid).IsValid()` per solid) finds N > 0 invalid solids.
Status snapshot 2026-10-01T21:11Z: **91 IFC models** carry it, **10,767 invalid solids** in total
(`models_invalid_solids.json` lists every model with category, counts, keys).

* 88/91 are **reused Disk-1/2 STEP files** (`ifc2step5.py --mode hybrid --prec 2`, old writer: no GlobalId in
  PRODUCT.id, join by name), 3 are z3 conversions (aa8a5888, ddaae9f3, f2a673aa).
* 79/91 have no other issue than `invalid_solids` (+ `non_positive_volume_solids`); 12 also `parts_outside_volume_tolerance`.
* By source / mechanism (counts of invalid solids):

| category | models | invalid solids | where |
|---|---:|---:|---|
| SDS/2 faceted source defects (bolts, welds, fasteners, HSS/pipe, plates) | 84 | 1,792 | transcode path |
| SDS/2 v2015.25 **"DWF Import"** reference meshes (`Member_Type: DWF Import`, weight 0, names `d1..dN`) | 3 | 6,829 | transcode path |
| Tekla 21.1 bolt assemblies (N cylinders in one product) | 2 | 1,886 | tess path |
| Revit bar joists / structural connections (chords + webs touching on edges) | 2 | 260 | transcode |

## 2. Root causes (proven on real samples)

The v5 converter copies source faceted geometry verbatim into one `FACETED_BREP`/`CLOSED_SHELL` per item (and writes
REALs with 9 significant digits). OCC's read-time healing (ShapeFix_Shell/Solid) cannot repair the defects below; it
either leaves invalid solids or - worse - **valid solids with wrong volumes**. Signatures were captured with
`tools/diag_step.py` (BRepCheck status per sub-shape of every invalid solid) and joined with the kernel-free mesh audit
`tools/mesh_audit.py` (edge-use, winding conflicts, components, signed volume per FACETED_BREP) by `tools/correlate.py`.

| # | BRepCheck signature (after OCC healing) | mesh defect in the STEP = in the source IFC | kind | example (model / part / evidence) |
|---|---|---|---|---|
| A | `face:BadOrientationOfSubshape` | single faces wound against their neighbours (edge used twice in the same direction) | source defect, not repaired by converter | 1ed73b05 `btp39_5`: IFC faces #2487, #2488 reversed vs #2486; OCC flips the shell but leaves the wire of the face against its plane |
| B | `solid:InvalidImbricationOfShells` + `SubshapeNotInShape` | SDS/2 weld = chain of closed triangular prisms sharing end faces (shared face twice, 4-use edges) | source defect | 063b7415 `weld-BP1_3`: 1 brep -> OCC makes **69 solids**, volume 1,514,614 mm3 vs true 57,668 (26x) |
| C | `solid:EnclosedRegion` + `SubshapeNotInShape` + `face:BadOrientationOfSubshape` (+`UnorientableShape`, `wire NotClosed`) | SDS/2 `PartLibFastener` (fst*): **double-sided** triangle mesh (each triangle twice, opposite winding; 1,230 pairs in fst4_1) + T-junctions (+ 1-2 tiny real gaps, + 0.01-0.02 mm micro facets on threads) | source defect | 0f73ae81 `fst4_1`: volume ~0, OCC leaves 23,612 loose shells, 17 parts without solid |
| D | `wire:SelfIntersectingWire` + `face:UnorientableShape` | none in the source: **converter bug** - `_r()` writes `%.9g`; state-plane coordinates (x=-4,777,444 ft, y=9,961,302 ft = 3.04e9 mm) are cut to a **10 mm grid** in the STEP, small faces fold | converter bug | 1481043e: 39 invalid, 124/152 parts > 5% volume off; STEP point `-1456164720.` vs true `-1456165078.79` |
| E | `solid:SubshapeNotInShape` | several disjoint closed pieces + lone zero-thickness faces in one shell (grating) | source defect | 032a7906 `gr113_3M` |
| F | **none - reported valid** | hollow sections: end-cap inner loop (`IfcFaceBound`) wound the **same way as the outer loop** | source defect, invisible to BRepCheck | 063b7415 `ts121_3` HSS6x4x3/16: OCC volume 66.4e6 mm3, true 13.15e6 (5.04x); 1771cfc9 `hss37` 10.9x |
| G | `face:UnorientableShape`, `InvalidImbricationOfWires`, 2-point wires | edges of 0.01-0.02 mm (output grid) on fine fastener meshes; OCC merges the vertices on read | converter (no weld below grid) | 09cbd0b8 `fst1_24` face 69 |
| H | `InvalidImbricationOfShells` / `EnclosedRegion` | Tekla bolt assembly: N cylinders (overlapping bboxes) tessellated into ONE closed shell | converter (tess output not split) | 03af2c31 `Bolt assembly`: 531/688 breps have >= 9 pieces |
| I | mixed | Revit joist chords + webs in one brep, touching along edges (3-4-use edges) | source + converter | 0fb40754 `K-Series Bar Joist` 180 breps `nonmanifold+multi+overlap` |
| J | all of the above | **DWF-import reference meshes** (SDS/2 2015.25 imported a DWF; all 1,798 products of 0ffd8af6 are `IfcMember`, `Member_Type 'DWF Import'`, `Material_Net_Weight 0`): open, double-sided surfaces, not solids | **genuine source defect** (not steel parts) | 0ffd8af6 / 02cab204 / 0d17e93c = 63% of all invalid solids |

Side findings (grader / measurement):
* `step_check` bbox is inflated by healing tolerances of the broken solids (vertex tolerance 82-394 mm on HSS/pipe/brep
  parts): 1ed73b05 bbox shrinks by 393.7 mm per side after the fix and then equals the point bbox to 0.01 mm.
* `invalid_solids:N` counts OCC solids after healing (one brep -> up to 229 solids), not parts.
* Category F is never caught: SDS/2 IFC has no quantity sets, so `ifc_census` has no `q`/`an` for these parts and the
  per-part volume check is skipped. SDS/2 `Material_Net_Weight` / 7849 kg/m3 is a usable cross-check (see 4.3) but too
  noisy for a 5 % rule (copes/holes are in the weight, not always in the geometry).

## 3. The fix: `patch/shellfix.py` (+ 3 small converter changes)

Kernel-free, deterministic repair of each closed shell **before** it is written (both transcode and tess paths), no
vertex moves more than 0.025 mm, unchanged shells are written byte-identically:

0. micro edges < 0.025 mm collapse (2.5 steps of the 0.01 mm output grid; OCC merges them anyway) [G]
1. inner loops wound against the outer loop (ISO 10303-42 rule) [F]
2. duplicated faces: exact repeats dropped; opposite twins -> **double-sided collapse** (keep one) when >= 75 % of the
   faces are twinned, else **internal walls removed** (both copies) - chosen only if it reduces non-2-use edges [B, C]
3. open shells: T-junction vertices inserted (collinear, polygon unchanged); remaining small holes filled with one
   planar face (fan on the loop's own vertices if not planar) only when the hole is < 10 % of the area of the faces
   around it and is not a copy of an existing face [C]
4. pieces = faces linked through 2-use edges; per piece an orientation walk (re-orient flipped faces) and outward
   orientation by signed volume about a local origin [A, B, E, H, I]; a piece wound inward in the source strictly inside
   another is kept as a void of it (not for double-sided meshes)
5. each closed piece -> its own FACETED_BREP; zero-area debris (< 1e-4 of the shell area) dropped; a remainder that is
   still not a closed 2-manifold -> OPEN_SHELL in a SHELL_BASED_SURFACE_MODEL (product rep becomes
   SHAPE_REPRESENTATION when mixed) instead of a FACETED_BREP that OCC reads as invalid solids [E, J]

Converter changes (`patch/ifc2step5_shellfix.diff`, same diff applies to the guard: `patch/ifc2step5_guard_shellfix.diff`;
patched files in `patch/kit/`, `worker_files_shellfix.diff` ships `shellfix.py` with the kit):
* `_r()`: `%.9g` -> `%.15g` (points are already rounded to `--prec` decimals, so only the lost digits come back) [D]
* `StepWriter.face()` split into `face_spec()` (cleaning, unchanged rules) + `emit_face()`; new `closed_breps()` runs the
  repair on rounded mm coordinates (exactly what OCC will read) and emits pieces; `part()` takes the open remainder
* transcode IfcFacetedBrep / closed Polygonal-/TriangulatedFaceSet and every tessellated product go through `closed_breps()`
* `--no-shellfix` restores the old output; `--nodedup` bypasses the repair; `stats.json` gets a `shellfix` counter block
* exceptions in the repair fall back to the old write (a part is never lost)

`patch/step_shellfix.py` applies the same repair to an existing STEP (text level, untouched entities copied) - for the
88 reused Disk-1/2 STEP files if they are not re-converted (it cannot restore digits lost to `%.9g`, i.e. 1481043e
needs re-conversion). `patch/test_shellfix.py`: 12 synthetic cases (all pass).

## 4. Evidence

### 4.1 Full pipeline A/B (real `worker.process` + `ifc_census` + `step_check` + `grade_join` + `build_index.classify_ifc`)
`tools/run_case.py` (copy of the improver's harness), kit + coord code **snapshotted** at 15:21 (`work/kit_snap`,
`work/coord_snap`) so both arms are graded by identical code; kernel ifcopenshell 0.9.0 / OCC 8.0.1;
`orig` = kit ifc2step5.py (md5 0548efad), `fix` = patch/kit/ifc2step5.py. Table: `results_ab_full_pipeline.json`.

| model | class orig -> fix | solids valid/total orig -> fix | orig issues |
|---|---|---|---|
RESULTS_TABLE

Valid parts that became invalid: **0** in all 19 models. Class-1 regression set (7 models, SDS/2 7.312-2020.11 +
Tekla 2020): all stay class 1.

### 4.2 Rewriting the reused Disk-1/2 STEP files (`tools/ab_run.sh`: step_shellfix + kit step_check before/after)
REWRITE_TABLE

### 4.3 Volumes against an independent truth
Every part whose volume changed was compared with SDS/2's `Material_Net_Weight` (lb) / 7849 kg/m3
(`tools/weight_truth.py`, pairs by GlobalId): WEIGHT_SUMMARY
The only parts that moved away from the weight are 1481043e c968_1/c969_1 (C8x11.5, 67 mm long): the fix gives
144,230 mm3 = analytic profile area x length (3.37 in2 x 2.64 in = 145,600 mm3); the SDS/2 weight (1.50 lb) includes
cuts not present in the IFC solid, and the orig value was produced from 10 mm-quantized coordinates.
For valid-before parts with volume drift, every drift checked is a correction (HSS/pipe 1.5-10.9x -> 0.99-1.00,
bolts with inverted pieces 122 mm3 -> 62,638 mm3, welds 26x -> 1x).

## 5. What it does not fix
* **DWF-import reference meshes** (category J, 6,829 invalid solids in 3 models): open double-sided surface soup; after
  repair a part becomes valid solids where it closes (0ffd8af6: 123 parts) and a surface otherwise, which the current
  grader reports as `parts_without_solid` (class 2). Faithful to the source; a class-1 outcome needs a grader policy
  (e.g. ifc_census tags SDS/2 `Member_Type == 'DWF Import'` with zero weight as reference geometry, not steel parts).
* Volume differences of solids that are valid and faithful to the IFC (e.g. weights that include copes).

## 6. For ifc2step6 (now deployed in the kit, `CODE ...+s6`)
v6 already does inner-loop winding, T-junctions, edge-connected components, orientation, voids, `%.2f` points
(precision OK) and verify-and-fallback. From this dive, still needed / to change in v6:
V6_NOTES

## 7. Files
* `patch/shellfix.py` - the repair (pure python)          * `patch/kit/` - patched ifc2step5.py / _guard.py (+ shellfix symlink)
* `patch/*.diff` - unified diffs vs `z3conv/ifc/`          * `patch/step_shellfix.py` - repair an existing STEP
* `patch/test_shellfix.py` - synthetic tests              * `models_invalid_solids.json` - the 91 models, categorised
* `results_ab_full_pipeline.json` - per model orig/fix    * `tools/` - diag_step, mesh_audit, correlate, badface,
  ab_run.sh/ab_compare, weight_truth, run_case/cases.sh, cases_table
* `work/` - downloaded samples, check outputs, case dirs (large, scratch)
