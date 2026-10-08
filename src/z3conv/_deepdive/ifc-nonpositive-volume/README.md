# IFC class 2 `non_positive_volume_solids` - root cause, fix, evidence

Owner of the fix: **ifc_improver** (writer patch / ifc2step6) + whoever runs the reused-STEP repair (see "Rollout").
All paths below are relative to `/Users/dhiren/Downloads/Deccan/z3conv/_deepdive/ifc-nonpositive-volume/`.

## TL;DR

* **It is a converter bug, not a grader bug, and not reversed orientation.** ifc2step5 copies an IfcClosedShell that
  holds *several bodies* into ONE STEP `CLOSED_SHELL` (ISO 10303-42: a closed_shell is a *connected* face set).
  SDS/2 (97 % of the affected models) exports a whole bolt (head, washers, shank, nut), a shear stud (head + shank) and
  a fillet weld (triangular prisms glued on coincident, opposite "mitre" faces) as one closed shell.
  OpenCASCADE's STEP reader (the consumer view the grader uses) heals such a shell by splitting it and **nesting
  touching / interpenetrating bodies as voids**: e.g. a bolt washer (4,408 mm3) + nut (16,282 mm3) come back as ONE
  solid with an outer and an "inner" shell, volume 4,408 - 16,282 = **-11,872 mm3**. Glued weld prisms (edges used
  4x) are shredded into 50-230 fragment solids, some inside-out, many `BRepCheck` invalid, total volume up to 26x the
  real bead.
* Single-lump shells are never the problem: 0 of the non-positive solids in 2,062 checked roots came from a
  FACETED_BREP with one closed lump. The hypothesis "inward normals / reversed shells" is not what happens (the
  one-lump inside-out case occurs only as a genuine source self-intersection, 2 solids in 1 model).
* **Fix (writer):** split every closed shell into its edge-connected lumps, one `FACETED_BREP` each; drop coincident
  opposite internal face pairs only where that leaves closed shells; keep open lumps together exactly as before; never
  re-orient (an `ORIENTED_FACE` inside a FACETED_BREP shell makes OCC 8.0.1 drop the solid - tested).
  `patch/ifc2step5.lumpsplit.diff` (+ the same for `ifc2step5_guard.py`), pure python, +~10 % convert time,
  +<1 % bytes. Same algorithm as a STEP->STEP repair for the **reused** Disk-1/2 STEPs (859 of the 1,273 current npv
  models are reused and will not change unless repaired or re-converted): `tools/split_lumps_step.py`.
* **Effect** (kit `step_check.py` + index-builder rules re-applied, details below): see "Quantification".

## 1. What the grader does (and why it is right)

`grade/step_check.py` reads every root with `STEPControl_Reader` (default shape healing), takes every `TopAbs_SOLID`,
`GProp` volume; `not (v > 0)` -> `nonpos_vol`. `coord/build_index.py` turns `nonpos_vol > 0` into the class-2 issue
`non_positive_volume_solids:N`. That is exactly what a CAD consumer using OCC (FreeCAD, CadQuery, any OCC viewer) gets:
wrong mass properties, voids that do not exist. No grader change is needed for classification.
Optional info-only patch: `patch/step_check.multishell.diff` adds `multi_shell_solids` (solids with >1 shell) so
reused STEPs with *hidden* nesting (volume still positive but wrong, see 3.4) can be found; it does not touch the class.
(The kit step_check.py is being edited by other agents; the diff is 9 lines, re-apply by hand if it no longer applies.)

## 2. Population (live index 2026-10-01T22:16Z)

* 1,273 IFC models carry `non_positive_volume_solids` (largest class-2 reason). 424 have it as their ONLY issue,
  631 also `invalid_solids`, 151 also `invalid_solids` + `parts_outside_volume_tolerance`, 41 + volume tolerance.
* Authoring app (census): SDS/2 1,237 (97 %), Revit 27, Tekla 9. Converter: ifc2step5 `--mode hybrid --prec 2` for all
  (859 reused from Disk-1/2, 2 from data-4, 412 new data-3 conversions).

## 3. Root cause, proven per solid

Tools: `tools/npv_classify.py` (each npv solid: shells, per-shell volume, free edges), `tools/step_lumps2.py`
(text-level: per FACETED_BREP edge-connected lumps, signed volume as written, closedness),
`tools/occ_roots.py` (per-root OCC solids `[volume, shells, valid]`), `tools/residual.py`, `tools/regress.py`.

### 3.1 Multi-lump closed shells (bolts, studs)  - the main cause
`data/c14e58` (ifc-14e58e8a..., SDS/2 2015, 14 parts): 14 FACETED_BREP -> OCC 36 solids, 3 npv. Each npv solid is a
bolt (`bolt-w3905_2`, one IfcFacetedBrep / IfcClosedShell of 104 faces in the source, 6 disconnected lumps:
36/14/18/8/14/14 faces). As written every lump has positive signed volume (10,435 / 4,003 / 4,408 / 16,282 / 3,681 /
3,601 mm3). OCC returns the 18-face and the 8-face lump (they interpenetrate) as one solid with 2 shells,
volume -11,872 = 4,408 - 16,282 (the 8-face lump made a void). `ShapeFix_Solid` on it does not change the sign.
`data/c236247`: 94/94 npv solids are shear studs `ss1` (head 20 faces + shank 14 faces touching face-to-face):
shell volumes [2216.6, -6372.8] -> -4,156 mm3.
Across 7 models (2,062 roots): every npv solid belongs to a multi-lump brep (`multi_closed` / `multi_with_open`) or
an open weld brep; `single_closed` breps: 0 npv.

### 3.2 Glued weld prisms (SDS/2 `weld-*`, IfcFastener)
`data/c063b74` `weld-f158_3`: 20 faces = 4 triangular prisms; two of them share coincident mitre triangles written
twice with opposite winding (source faces 1 / 17 and 7 / 16) -> 12 edges used 4x. OCC: 6 solids, two of -10.8 mm3,
area negative. `weld-BP1_3` (140 faces): OCC 69 solids (shells up to 15), total 1,514,614 mm3 vs 57,673 mm3 as
written; after the fix 1 solid, 57,668 mm3. 42 of the 42 invalid solids of this model are such weld fragments.

### 3.3 What is NOT the cause / genuine source defects left over
* `data/c061413` `ch40` / `ch45`: one closed, consistently oriented lump, as-written volume +147,809 mm3, OCC -147,809:
  the channel's oblique end cut crosses its other end plane (self-intersecting "bow tie" body in the SDS/2 source).
  OCC's inside-out test flips it. Genuine source defect; stays class 2 (correctly).
* Double-sided open sheets (SDS/2 library fasteners `fst1_24`, every facet twice with opposite winding, no closed
  inside): zero volume in the source. Left as they were by this patch (no regression); ifc2step6 writes them as
  tagged surface models.

### 3.4 Hidden error in "good" roots
Bolts whose mis-nested solid still has positive volume are under-counted today without any flag: e.g. c14e58 roots
10/11: OCC 34,405 mm3 vs 42,411 mm3 actual (as-written lump sum; after fix 42,411). 49 such roots in 7 models,
70 in 11 (all corrected to the as-written volume, or a solid gained where OCC produced none). This also affects
class-1 SDS/2 models (no expected volumes in SDS/2 IFCs, so the grader cannot see it).

## 4. The fix

### 4.1 Algorithm (`patch/lumpsplit.py`, inlined into the writer as `_split_lumps`)
1. edge-lumps = faces joined across any shared edge (vertex-id pair; the writer's point cache dedups at --prec, exactly
   the sharing OCC's StepToTopoDS builds);
2. inside a lump, coincident opposite face pairs are dropped **only if** every remaining piece is closed (weld mitre
   faces, bolt parts sharing a face); else the lump is untouched;
3. an edge with >2 uses and balanced orientation is resolved by radial ordering (pair each half-edge with the next face
   rotating into the solid); if that would leave an open piece the lump stays whole;
4. every closed lump -> own FACETED_BREP; all open lumps stay together in one shell, as written before;
5. a closed inward lump strictly inside (bbox) a positive one stays in its shell (void semantics kept);
6. never re-orient, never rewrite a face: the written entities are byte-identical to v5 except the CLOSED_SHELL /
   FACETED_BREP grouping (and unreferenced internal faces).

### 4.2 Files
| file | what |
|---|---|
| `patch/ifc2step5.lumpsplit.diff` | drop-in diff against `ifc/ifc2step5.py` (md5 0548efad... at time of writing) |
| `patch/ifc2step5_guard.lumpsplit.diff` | same hunks against `ifc/ifc2step5_guard.py` |
| `patch/ifc2step5.py`, `patch/ifc2step5_guard.py` | patched copies (single file, no new import) |
| `patch/lumpsplit.py` | the algorithm as a module (used by the repair tool and tests) |
| `tools/split_lumps_step.py` | STEP->STEP repair of an existing ifc2step FACETED_BREP file (reused STEPs) |
| `patch/step_check.multishell.diff` | optional, info-only grader counter |

Writer switches: on by default; `IFC2STEP_NO_LUMP_SPLIT=1` or `--nodedup` disables it. stats.json gets
`lump_split {breps_split, breps_written, cancelled_faces, cancel_rejected, open_lumps_kept_together, radial_edges, ...}`.

## 5. Evidence (before / after, kit step_check, OCC 8.0.1 / ifcopenshell 0.9.0 = fleet env)

EVIDENCE_TABLE

* `fleet` = the fleet's validate block; `split4` = the reused/fleet STEP repaired with `tools/split_lumps_step.py`;
  `wA` / `wB` = the kit `ifc2step5.py` vs the patched writer run on the source IFC with the fleet flags;
  `sfx` = sibling deep-dive `ifc-invalid-solids` `step_shellfix.py` (snapshot md5 da586c69 / shellfix 697d06aa);
  `v6` = ifc_improver `ifc2step6.py` snapshot (md5 9d8ef8d9). Cell = solids / invalid / **non-positive**.
* Patched writer == repair tool: per-root OCC volumes identical for all 2,062 roots of the 7 base models.
* Per-root regression (`tools/regress.py`, key = PRODUCT id): REGRESS_LINE
* Render ink unchanged on every case except c148104 (0.155 -> 0.109): 21 bolt parts that OCC used to drop
  completely now come back as solids and widen the drawn extent (more geometry, not less).

## 6. Quantification

QUANT_BLOCK

## 7. Rollout

1. New conversions: ship the writer patch (or ifc2step6, which contains the same split + contact-wall removal, see
   cross-check) - nothing else needed.
2. Reused Disk-1/2 STEPs (859 of 1,273 npv models; also the class-1 SDS/2 reused ones with hidden under-volume):
   either re-convert them (the source is in the bucket, transcode is seconds) or run
   `tools/split_lumps_step.py IN.stp OUT.stp` (pure python, ~8x file size RAM, ~0.2 s/MB) and grade the repaired copy.
   The batch harness `tools/batch_one.sh` shows the exact sequence (download -> repair -> step_check -> grade_join).
3. Grader: no change required; optionally the info counter.

## 8. Cross-check of the other implementations (for the ifc_improver)

XVAL_BLOCK

## 9. Notes / caveats
* `ORIENTED_FACE('',*,#f,.F.)` inside a FACETED_BREP `CLOSED_SHELL` -> OCC 8.0.1 drops the whole solid (tested on a
  6-face plate in c14e58: 1 solid -> 0). Any orientation repair must rewrite the POLY_LOOPs (shellfix does).
  ifc2step6 writes voids as `ORIENTED_CLOSED_SHELL(.F.)` in BREP_WITH_VOIDS - worth one read-back test with a real void.
* `IfcFacetedBrepWithVoids` voids are still written by v5 (and by this patch) as separate positive solids (void becomes
  material). Not present in any sampled npv model; ifc2step6 fixes it.
* Process note: at ~15:05 local, while stopping my first batch, I ran `pkill -f "step_check.py /Users/dhiren/Downloads/
  Deccan/z3conv/_deepdive"` and `pkill -f "xargs -P"`; these patterns also match processes of other deep-dive agents
  (ifc-invalid-solids was running step_check on its cases at that time). If one of their checks from ~15:05 is missing
  a check.json, that is the reason; re-running it is enough.
