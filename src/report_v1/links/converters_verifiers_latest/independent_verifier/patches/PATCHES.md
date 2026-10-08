# Grader patches ported from ifc-step-verifier / db1-step-verifier (z3v-2026-10-02a)

Against the kit copies of 2026-10-02 (step_check.py md5 e3fca13d…, build_index.py as of 11:43Z). The full patched files are
included, compiled, and tested: step_check on 2 test STEPs plus a truncated copy.

## step_check.py (step_check.py.diff), new output keys
1. File integrity (F_NOT_STEP / F_COMPRESSED / F_TRUNCATED / F_SCHEMA): `iso_header`, `compressed`, `end_marker`,
   `schema_geometry`. OCC reads a cut-off file up to the cut, so END-ISO-10303-21 is the only proof of completeness.
   Tested: a 2 MB cut of a 4.7 MB STEP gives end_marker False.
2. W_BROKEN_SOLID: `impossible_solids` and `impossible_examples`. Fires when a checked root's solid volume exceeds its own
   bbox × 1.001, the signature of hole loops wound like the outer loop. Such a solid passes BRepCheck but is
   self-overlapping.
3. Duplicates: `duplicate_pid_parts` (a product written twice under the same source id) and `coincident_duplicates`
   (same bbox centre at 0.1 mm and same volume at 10 mm3; DB1 W_DUPLICATES).
4. W_STRAY_PARTS / W_FAR_STRAY: `stray_parts`, `stray_examples`, `core_extent_mm`. This is the DB1 verifier's _strays,
   unchanged. It needs scipy; the conda env has none, so it reports `stray_check: unavailable`. Add scipy to setup_occ.sh
   to enable it.

## build_index.py (build_index.py.diff). Keys absent on older read-backs have no effect.
- reasons (class 3): step_truncated, step_not_iso10303_21, step_compressed, step_schema_not_geometry
- issues (class 2, converter_feature):
  - solids_volume_exceeds_bbox:n
  - step_duplicate_parts:n
  - step_parts_not_in_source:n (W_EXTRA_PARTS, gid join only; 0 of 300 sampled class-1 IFC models have any)
  - DB1 only: stray_parts:n when more than 0.5 % of roots, coincident_duplicate_parts:n when more than 5 %
- IFC strays and coincident duplicates: info only, because each part keeps its own source GlobalId.
- explain(): categories and fix texts for each new issue.

## Rules found by the verifier on the tests (not coded yet; proposed)
5. A missing element voided by its own opening counts as SOURCE.
   - Case: e1828d1ce27d, our class 2 "converter_feature | ifc missing parts". The missing IfcMember pp11852
     (1tZBDdDY13vwqNCtuYcC8s) has an IfcOpeningElement (0U5poK5$1GZAKTOc6OmcKC) with exactly the member's extent.
   - IfcOpenShell builds 208 triangles with openings disabled and 0 with them. The source cuts the whole member away, so
     the empty result is faithful and the model is otherwise complete.
   - Port: for each missing gid (cap 200), run `ifcopenshell.geom.iterator(settings(use-world-coords), f, 1, include=[e])`
     with and without `disable-opening-subtractions`. Empty with openings but non-empty without means
     source_voided_by_openings: leave it out of expected (info).
   - Elements that IfcOpenShell cannot build even without openings: keep as converter_feature. The verifier calls those
     SOURCE; I do not, because our converter uses the same kernel.
6. Surface parts that are surfaces in the source get category source_data_absent instead of converter_feature.
   - Case: f9480fa917e4. Both "parts without solid" are IfcShellBasedSurfaceModel in the source; the verifier says
     W_OPEN_SHELL_SOURCE.
   - Our converter tags these itself: v6 tag open_in_source 2.
   - The class stays 2 (validity unprovable). Only the explain() category changes, for parts_without_solid and
     v6_L4-surface where the census `rt` is SurfaceModel or v6 open_in_source covers them. This affects many of the 1,579
     "ifc parts without solid" models.
