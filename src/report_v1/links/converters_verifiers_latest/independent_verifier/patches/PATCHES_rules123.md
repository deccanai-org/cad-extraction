# IFC rules 1-3: coded (z3v-2026-10-02b), requested by main 2026-10-02

New helper `ifc_attrib.py` (kit file; runs in the conda env with ifcopenshell 0.9.0, in PY84 with 0.8.4, or in the verifier
venv with 0.8.5; tested on 0.9.0 and 0.8.5):
- usage: `ifc_attrib.py SRC SRC_PARTS STEP_PARTS OUT.json [--unpack-dir D]`
- SRC is the source object as stored. It is unpacked and schema-fixed the way ifc/worker.py does it.
- It looks only at the problem parts of the census / STEP join:
  1. STEP parts without a solid (grade_join surface_parts). Each gets the ifc-step-verifier source_state of its IFC element
     (mapped items unwrapped):
     - surface_model: only IfcShellBasedSurfaceModel / IfcFaceBasedSurfaceModel / IfcOpenShell items, or face sets with
       Closed = False.
     - faceted_open: an IfcFacetedBrep whose edges are not each shared by exactly two faces.
     Both give cause source. Everything else gives cause pipeline.
  2. Source parts missing from the STEP. IfcOpenShell builds the element alone, with and without opening subtraction.
     It is `voided` (source_element_fully_voided, cause source) when the result is empty with openings, non-empty without,
     and one of the element's own IfcOpeningElements covers its whole extent (0.5 mm tolerance). Otherwise it is
     buildable / cut_empty / not_buildable (pipeline). not_buildable stays pipeline because our converter uses the same
     kernel.

build_index.py (in build_index.py.diff, together with the earlier ports):
- `ATTRIB` is loaded from `_state/conv/ifc/attrib/<id>.json`, the fleet job for existing results. A worker-embedded
  `rec['attrib']` takes precedence.
- Rule 1: voided elements leave expected, with coverage recomputed per category. They are recorded as
  issues_info `source_element_fully_voided:n` (cause source) plus `row.source_fully_voided`.
  - e1828d1ce27d before: class 2 (coverage 0.9818, `converter_feature | ifc missing parts`).
  - After: class 1 (coverage 1.0).
- Rules 2 and 3: `parts_without_solid:n` is split into `parts_without_solid:n_pipeline` (converter_feature, as before) and
  `parts_without_solid_source:n_source` (source_data_absent, "ifc source surface models"). These stay class 2.
  - The standins v6_L4-surface and v6_L3-partial-surface: the source share goes to source_data_absent, the rest stays
    converter_feature.
  - v6_open_in_source_healed (the converter's own evidence that the source shell is open) goes to source_data_absent.
  - f9480fa917e4 before: class 2 [converter_feature | ifc parts without solid, converter_feature | ifc v6_L4-surface].
  - After: class 2 [source_data_absent | ifc source surface models].
- Without attribution data nothing changes; all surface parts count as pipeline, as before.

Worker hooks (ifc_worker.py.diff, grade_worker.py.diff):
- After the join, run ifc_attrib.py when the join shows surface parts or coverage < 1.
- Store `rec['attrib']` and upload `attrib.json` to the detail prefix.
- Add 'ifc_attrib.py' to FILES.

Existing results: `ifc/attrib_jobs.jsonl` holds 1,587 jobs (1,493 surface only, 86 surface + missing, 8 missing only;
139.7 GB of sources).
- Each job: `{id, input_key, src_parts_key, step_parts_key, out_key=_state/conv/ifc/attrib/<id>.json, size}`.
- The job: download input_key plus the two detail files, run `ifc_attrib.py`, upload OUT to out_key.
- Memory is about that of ifcopenshell.open: roughly 10 x the source size, plus 1 GB.

## Split of "ifc parts without solid" (1,579 models, 396,636 surface parts): first estimate
- From the detail files alone (census RepresentationType of each surface part's source element), the split is inconclusive:
  - 7,709 parts are certainly source (SurfaceModel);
  - 20 are certainly pipeline (SweptSolid / CSG);
  - 335,054 come from MappedRepresentation sources, whose real item type needs the source file;
  - 33,676 are unpaired.
- ifc_attrib.py on a random sample of 40 models with sources ≤ 15 MB (456 eligible):
  - 7 were reused old-writer STEPs without GlobalIds, so no per-part attribution (name join).
  - Of the 33 GlobalId-joined models: 27 all source, 5 all pipeline, 1 mixed.
  - Parts: 100 source (76 faceted_open, 24 surface_model) vs 21 pipeline (12 faceted_watertight, 9 other_solid), about 83 %
    source.
  - Missing parts in GlobalId-joined models: 1 model, 1 element, buildable, so pipeline (410b3c2decb3, IfcBeam 7071G2).
- Caveat: faceted_open uses the verifier's rule (edges not shared by exactly two faces, points rounded to 6 decimals). It
  also counts T-junction meshes that a converter might still close; that share is the faceted_open number.
- The full split comes from the fleet job over ifc/attrib_jobs.jsonl: 1,348 GlobalId-joined models, 129.1 GB of sources.
  The 239 name-joined, old-writer reused models keep converter_feature (fix: re-convert with the current writer).

## v2: ifc_attrib_v2.py (z3v-2026-10-02d; main 2026-10-02). The open-shell test resolves T-junctions first.
- This mirrors ifc2step6 6.1.x at --prec 2: vertices are welded to the 0.01 mm grid, then boundary edges are split at
  boundary vertices lying on them (<= 0.02 mm, Repair.tjunctions ported; no faces added), then closure is decided on
  free edges (edges used once).
- States:
  - `faceted_open`: free edges remain, so source (real free edges).
  - `faceted_tjunction_closed`: closes only after the split, so pipeline.
  - `faceted_watertight`: closed as given or after welding, so pipeline.
  - Surface models: `surface_model_open` is source. `surface_model_closed` (all shells close) is source by default,
    per rule 2; pass `--closed-surface-models pipeline` to apply the free-edge principle to them too.
  - Each part also carries its v1 state, so `surface.v1` and `surface.moved_vs_v1` give the change in one run.
- Not applied: 6.1.x also sews seam vertices within 0.1 mm before the T-junction pass. Shells that would close only by
  sewing stay faceted_open.
- Synthetic tests:
  - closed cube: closed;
  - T-junction cube: 6 free edges, 2 vertices inserted, then closed;
  - vertex 5 µm off the edge: closed;
  - one face missing: open (4 free edges);
  - 0.5 mm gap: open.
- Output schema: as v1, plus fields. build_index needs no change.
- To switch: use `ifc_attrib_v2.py` instead of `ifc_attrib.py` in FILES and in the hook command.
- Sample results, v1 -> v2 (parts are STEP surface parts paired with their source element by GlobalId):
  - Original v1 sample (32 GlobalId-joined models):
    - models (all source / all pipeline / mixed): 26 / 5 / 1 -> 23 / 8 / 1
    - parts: 98 source / 21 pipeline -> 83 / 36 (82 % -> 70 % source)
    - 15 parts moved: 10 close after the T-junction split, 5 close at the 0.01 mm weld
  - A second random sample (40 GlobalId-joined models, sources <= 15 MB):
    - models: 35 / 4 / 1 -> 32 / 6 / 2
    - parts: 138 / 17 -> 126 / 29 (89 % -> 81 %)
    - 12 moved: 3 by the T-junction split, 9 by the weld
  - In the second sample, 36 of 59 surface-model parts have closed shells. Under --closed-surface-models pipeline that
    sample gives 90 source / 65 pipeline (58 %); models 30 / 7 / 3.

## v2 final (z3v-2026-10-02e; main's decision 2026-10-02)
- **The full 6.1.x repair chain runs before closure** (it adds no face), on every shell:
  1. weld to the 0.01 mm grid;
  2. dedup faces (identical faces and contact walls; port of Repair.dedup_faces);
  3. keep one side of a double-sided mesh (twins >= half the faces);
  4. sew boundary vertices within 0.1 mm (port of Repair.sew; zero-area faces dropped; kept only if open edges decrease);
  5. dedup again;
  6. split T-junctions.
  Free edges remaining afterwards are source; otherwise pipeline.
- New state: faceted_sew_closed.
- `--closed-surface-models` now defaults to **pipeline**: a surface model whose shells all close is a closed volume, so
  writing it as a surface is converter work.
- Each part's v1 state is still recorded.
- Synthetic tests:
  - closed cube: watertight;
  - T-junction cube: closed after the split;
  - 0.05 mm corner seam: closed by sewing;
  - double-sided sheet: open (single-sided);
  - one face missing: open;
  - 0.5 mm gap: open.
- **Final sample result** (both samples, 67 distinct GlobalId-joined models, sources <= 15 MB):
  - Parts: v1 229 source / 35 pipeline (87 %) -> final v2 166 / 98 (63 %).
  - Models (all source / all pipeline / mixed): 58 / 7 / 2 -> 50 / 13 / 4.
  - Original 32: 98 / 21 -> 83 / 36; models 26 / 5 / 1 -> 23 / 8 / 1. Sewing merged 429 seam vertices but closed no further
    shell in these samples.
  - Final states: source = faceted_open 121 + surface_model_open 45. Pipeline = faceted_watertight 26 +
    faceted_tjunction_closed 13 + other_solid 23 + surface_model_closed 36.
- **Converter work list:** `attrib_pipeline_list.py --s3-prefix cad-disk-extract/zenitude-data-3/_state/conv/ifc/attrib/ --out
  LIST.jsonl --index index.jsonl.gz`. Each line: model id, pipeline part counts by state, example GlobalIds, class, code.
  - Sample: 18 of 67 models (tests/attrib_v2e_pipeline_worklist_sample67.jsonl).
- **Hooks for v2:** patches/ifc_worker_v2.py.diff and grade_worker_v2.py.diff (identical to the v1 hooks, with ifc_attrib_v2.py).
