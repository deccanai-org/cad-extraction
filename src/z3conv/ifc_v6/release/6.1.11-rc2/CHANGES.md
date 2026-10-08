# ifc2step6 changes (vs ifc2step5)

Drop-in: same CLI (`IN OUT --mode hybrid|transcode|tess --threads N --prec N [--nodedup --noplane --gzip]`), same flavour
(AUTOMOTIVE_DESIGN, FACETED_BREP / POLY_LOOP, no ADVANCED_FACE / tessellated entities), same PRODUCT mapping
(id = GlobalId, name = Name, description = IFC class), same `<out>.stats.json` + stats JSON on stdout. Runs on the kit env
(ifcopenshell 0.9.0 + pythonocc 8.0.1); under the 0.8.4 venv it finds `../env/bin/python` for verification.
`ifc2step6_guard.py` is an identical copy (the corrupt-coordinate guard is built in).

## 6.1.11 (rc2)

- **Closed surface models are written as solids.** Applies to a surface-model item (IfcFaceBasedSurfaceModel,
  open-shell IfcShellBasedSurfaceModel, open face set) whose faces form a closed, non-flat component enclosing real
  volume (volume / area^1.5 > 1e-6).
  - No face is added or moved. Info tag surface-model-closed.
  - Double-sided or zero-thickness sheets stay faces.
  - Example: 7013ded9, Revit concrete beams and pan joists: 11 surface parts -> 0, all 3,895 parts L0.
  - Opt-out V6_NO_SURFACE_MODEL_SOLIDS=1.

### 6.1.11-rc

- **Exact opening cut with curved tools.** When a kernel product's cut comes out open:
  - an opening tool that is not a faceted item or polygon extrusion (e.g. a drilled hole, a circle-profile extrusion)
    is taken as the kernel's own B-rep of the opening (true cylinder) in world millimetres;
  - a curved body is taken as the kernel's own B-rep of the body with its openings left out
    (disable-opening-subtractions);
  - the OCC cut result is then meshed, tagged exact-opening-cut + approx-curved, and kept only when it closes.
  Example: 1ea774eb pp11304 (faceted pipe, 5 drilled holes): L4 -> closed solid, 1,212,259 mm3 against a body of
  1,213,482 mm3. The 1ea774eb model goes from L4 3 to 0.

## 6.1.10

Final = 6.1.10-rc (canary 6.1.9-ctl vs 6.1.10-rc: 22 of 29 models, 0 regressions, controls unchanged).

### 6.1.10-rc

- **Planarity acceptance 0.05 mm** (5 grid steps at prec 2; V6_PLANAR_TOL_MM).
  - A source polygon stays one planar face when every vertex lies within 0.05 mm of its plane. Welding to the 0.01 mm
    grid alone moves planar source faces up to ~0.017 mm off their plane.
  - Before, faces 0.011-0.013 mm off-plane were triangulated, and the triangulation broke the T-junction fit. Examples:
    f7664cd2 B_99 / B_101 / B_102, and B_240 in the 11880e18 / 3063a0bc / d4fd5962 / fd0bb59a models. These now close.
  - The coplanar merge keeps 0.01 mm, so polygons are not merged more widely.
- **Pinch split.** A closed shell that touches itself along an edge (an edge used by 4 faces, no free edge) gets its own
  vertex copy per face fan at each pinched vertex. No face is added and no vertex moves. Info tag pinch-split. Example:
  weld-3W553 in 8786a843 / f74d0694 is now closed. Opt-out V6_NO_UNPINCH=1.

## 6.1.9

Final = 6.1.9-rc plus a time budget on the exact fallbacks (exact opening cut / exact body), V6_EXACT_OPEN_BUDGET_S,
default 900 s per run.

### 6.1.9-rc

- **Exact polygon-extrusion fallback.** A kernel product whose body comes out open is rebuilt from its own items when
  every item is a faceted item or an IfcExtrudedAreaSolid of a polygon profile. Polygon profiles are
  IfcArbitraryClosedProfileDef / IfcArbitraryProfileDefWithVoids of IfcPolyline, and IfcRectangleProfileDef. The
  prism is built exactly: two caps and one quad per profile edge. It is kept only when it closes.
  - Example: f9a54177 p16813. Its profile has a 0.01 mm edge, and the kernel dropped both caps. The prism is
    172,939 mm3, and the 3 instances are now L0.
  - The fallback also applies to the shared geometry of instanced parts. Opening tools that are polygon extrusions are
    now accepted by the exact opening cut.
  - Info tag exact-extrusion; stats exact_opening_cut {body:*, inst:*, open:*}.
- **L1 proof record.** When L1 is written, parts.json carries l1_planar_exact (bool) and l1_check with these fields:
  - same_vertices_as_l0: hash of the written vertex set against the last world-coordinate L0 / L0c attempt. L1 is
    triangulate_all of those faces, so each triangle lies in its L0 face's plane.
  - l0_failed_as;
  - l0_volume_mm3, volume_mm3, volume_diff_mm3;
  - volume_tol_mm3 = output grid step x face area;
  - curved_source;
  - rmax_mm.
  This is for the grader's per-part rule (b): far-coordinate planar L1 parts are exact. Sidecar only; geometry is
  unchanged.

From the verifier's pipeline parts_without_solid list (aa22160f):
- **Multi-face contact walls.** A contact wall between touching solids that is given as many faces (e.g. the kernel's
  triangulated cut of a beam with 18 copes and holes, 786aab37 w252: 126 twin triangles) is now removed as a region:
  - twin pairs joined by shared edges form one region;
  - the region goes when every rim edge is used twice by faces outside all pairs, and no edge is used other than 0 or
    2 times outside them;
  - result: the exact union, no surface added.
  Before, the per-pair rule needed every edge of a pair used twice outside, so walls of many faces stayed and the part
  fell to L4. Stats contact_wall_regions_removed. Opt-out V6_NO_WALL_REGIONS=1. 786aab37 locally: 7 L4 beams -> exact L0,
  all 2,167 parts L0.
- **Exact opening cut.** When the kernel's cut of a faceted body comes out open but the body itself closes, the
  openings are cut by OCC (BRepAlgoAPI_Cut) from the exact transcoded body and the transcoded opening solids, through
  this converter's own STEP writer and reader. Example: ecae31e1 w18078, where the kernel dropped faces of the body
  itself (22 free edges even without openings). When every face of the result is planar with straight
  edges (faceted body, faceted openings), its face wires are the exact polygons; otherwise it is meshed on its faces.
  It is then rebuilt like a kernel product. 48ca623d a2588 / a2592 (mesh failed in the first version) are replaced too. Info tag
  exact-opening-cut; stats exact_opening_cut {replaced, why}. Opt-out V6_NO_EXACT_OPEN=1. ecae31e1 locally: L4 ->
  exact L0, 1 solid, 125 faces.

## 6.1.8

Final = 6.1.8-rc plus two sewing decisions (coordinator, 2026-10-02):
- **Seam sewing never moves a vertex by more than its tolerance.** 6.0-6.1.8-rc merged boundary vertices within tol_sew
  (0.1 mm at prec 2) through union-find chains, so a chain a-b-c could move c by more than 0.1 mm: up to 0.33 mm, on 247
  parts in 11 class-1 models. Now leader clustering: in x order, an unassigned boundary vertex keeps its place and takes
  every unassigned boundary vertex within tol of itself. Measured on the 145 class-1 models with sewn parts (1,177
  parts, build only):
  - no part changes closedness;
  - largest volume change 7e-5;
  - sew_max_mm <= 0.1 everywhere.
  Opt-out V6_SEW_CHAIN=1 (old behaviour).
- **Closed within tolerance = 0.1 mm** (GAP_CLOSE_MM, V6_GAP_CLOSE_MM; was 0.01 in the rc), the converter's declared sew
  tolerance. On the 62 OIS models it closes nothing more (no remaining gap is under 1 mm).
- Grader rule (keyed on sidecar values only, never on OCC's read-time healing):
  - sew_max_mm <= 0.1: exact, info `sewn:<max>`;
  - gap_max_mm <= 0.1: closed by the converter, untagged;
  - other open shells keep open_in_source.

### 6.1.8-rc

Exact topology repairs for open-in-source shells, a reader-killing degenerate face, and an unmerged retry before L1.
No face is added, and no vertex moves by more than the existing grid weld / seam sewing.
- **Zero-width spikes cancelled.** A collinear tail (the boundary runs out and back along one line) becomes a -> b -> a
  once its T-junction vertex is in. It is now cancelled (stats spike_vertices_removed), which closes e.g. 33137cdc
  ts173_5M and 0dc425d4 TMP3002 (open_in_source before). Opt-out V6_NO_DESPIKE=1.
- **Zero-area faces.** earcut projected absolute coordinates and kept collinear ears. Such a face was written with
  DIRECTION (0,0,0), and OCC then raised on the whole FACETED_BREP and dropped it (410b3c2d beam 7071G2: 2,485 faces
  read back as none, so the grader counted the part missing).
  - earcut now works relative to a face vertex, with a relative collinearity threshold.
  - Zero-area faces are dropped before the T-junction split (stats faces_zero_area_dropped_late).
  - The writer never writes a zero direction (stats faces_zero_area_skipped_at_write; expected 0).
  - Opt-out V6_NO_DEGEN_FIX=1.
- **Flat closed shells.** A closed component with every vertex in one plane (zero volume, a patch covered from both
  sides) is written as faces, not as a solid (stats flat_closed_shells_as_surface).
- **Coincident faces by orientation count.** A face cycle given more often in one orientation than the other keeps one
  copy of the majority orientation (stats coincident_faces_net_resolved). Example: an SDS/2 stud end cap given 3 times,
  2 outward + 1 inward (a80c9618 ths1, c1de5e51 ts2). Example: the kernel's cut of an HSS with 10 holes (d00047d0
  hss4082: faces 1:5 / 2:1 per cycle). Before, the 3 copies became 2 opposite ones and the shell stayed open.
  Opt-out V6_NO_NET_DEDUP=1.
- **Overlapping coplanar faces -> signed union** (info tag coplanar_overlap_merged).
  - The shell's coplanar faces at a bad edge (free, or used by 3+ faces) are replaced by the cells of their arrangement
    whose orientation sum is >= 1 or <= -1. The faces are grouped within 0.05 mm; non-planar unions are split on
    their own vertices.
  - It applies before seam sewing (kept when the bad edges decrease) and on open shells (kept when the shell closes).
  - A group whose faces cancel to zero over a covered cell is left alone: contact walls and double-sided sheets keep
    their own rule.
  - Examples: 475f982e B_448 (two end faces overlapping in a 0.07 mm strip), 324c0e0e p8472 (three end faces, one
    cancelling the overlap), 6260e106 911B5. Needs shapely; skipped without it. Opt-out V6_NO_COPLANAR_UNION=1.
- **Open shell measure.** For every shell still open, the sidecar parts.json records:
  - gap_max_mm: for each free edge, the max over 5 points of the distance to the nearest other free edge; null when a
    free edge has no partner;
  - open_shell: {free_edges, nonmanifold_edges, gap_any_mm, closed_within_mm}.
  A shell whose every free edge lies within 0.01 mm (V6_GAP_CLOSE_MM) of another is closed at that tolerance and
  written untagged. Others keep open_in_source. stats.json: open_source_shells {parts_open_in_source,
  parts_closed_within_tol, gap_max_mm_hist}.
- **sew_max_mm.** Per part, the largest vertex move of the seam sewing (boundary vertices merged up to 0.1 mm at prec 2)
  goes into the sidecar. stats.json gets sewn_parts {parts, sew_max_mm, sew_max_mm_hist}.
- **Representation tags follow the written representation.** An L1 shell that closes no longer carries the failed L0
  attempt's open_in_source.
- **L0c: unmerged retry.** A part whose L0 had coplanar triangles merged (merge_coplanar) and failed the read-back is
  retried with its own faces before L1. This is exact, with no tag (stats L0c_unmerged). Opt-out V6_NO_L0C=1.
- **L1 for lost open shells.** L1 is now also tried for open source shells the reader lost; 6.1.7 skipped them. A
  triangulated shell can close (410b3c2d 7071G1).

## 6.1.7

- **Verify time budget.** The per-part read-back of the largest models (six 1.1-1.2 GB Tekla 2022 IFC) ran past the
  worker's limit, which then restarted the whole conversion on the 0.8.4 kernel. The verify phase now has a budget:
  default 2 h (V6_VERIFY_BUDGET_S), and never past 85% of the job's total wall budget (V6_TOTAL_BUDGET_S, else the
  worker's IFC_TIMEOUT_S when set). When it is used up the read-back stops: parts already read back keep their verdicts
  and fallbacks, the rest are written as converted (L0) with tag verify_partial; no fallback stage starts afterwards;
  stats verify_partial {parts}, verify_budget_exhausted, verify_budget; verify_parts.jsonl.gz marks them
  verify_partial. The grader's own read-back (step_verify_big) decides their class. The converter exits rc 0, so the
  worker does not restart on 0.8.4.
- **Fork isolation only on Linux.** On macOS forked children of a process with ifcopenshell / OpenCASCADE loaded can die
  at once (healthy products were excluded as kernel_memory_exceeded in local tests); elsewhere the kernel runs
  in-process. The fleet (Linux) is unaffected.

## 6.1.6

- **Opening-tool repair is retry-only.** 6.1.2-6.1.5 removed contact walls from the opening shells of every kernel
  product before the kernel pass (ifc-volume-residue patch 1); the independent verifier found that on SDS/2 v2020
  pipe-cope models it lost 36 valid parts (7ec85dca / 1ea774eb / c8f3e1a6: coverage 1.0 -> 0.95) and turned 60 valid
  solids into open surfaces, with 231 of 330 repaired shells still non-manifold (guard bad1 < bad0). Now the repaired
  tools are used only for a product with openings whose kernel result with the ORIGINAL tools is empty: those products
  are run once more with the repaired tools (tag opening-tool-repaired, stats opening_shell_repair.recovered) and the
  original tools are restored afterwards. Every other product keeps its original result. Opt-out V6_NO_OPENING_REPAIR=1.
- **Far mode hard-off.** Far-mode output read in place was invalid on far models (f451e1f2: 9,243 of 13,093 solids;
  15,060 of 38,646 overall vs 1 of 38,640 in normal mode). V6_FAR_VERIFY is now ignored (stats far_verify notes it);
  V6_FAR_VERIFY_TEST=1 enables the far round for tests only.

## 6.1.5

- **Tag semantics: stray faces.** A part that is a valid solid but also carries loose source faces (open components
  with more than half their edges free, e.g. a tread pattern not stitched to an SDS/2 floor plate) keeps those faces as
  faces with the info tag `stray-faces`; `open-surface` (a description tag, counted as a stand-in by the grader) is now
  only set on parts that have no solid. Regression found in the 81-model run: class-1 control 019e0c5c went 1 -> 2 under
  6.1.3 only because of that tag (4 plates: 1 valid solid + 119 loose faces each); with 6.1.5 it is class 1 again.
  Geometry is unchanged.

## 6.1.4

- **Main kernel pass in memory-capped children.** ifcopenshell 0.9.0's iterator accumulates memory over a long run
  (Tekla 2022 746974a2 / 4efa1dc5: 150 GB / 90 GB in 6.1.2's kernel tail). The kernel products now run in groups of
  500 (V6_KERNEL_GROUP), each in a forked child capped at VmSize + 16 GB (V6_KERNEL_GROUP_GB) with a stall timeout
  (V6_KERNEL_STALL, 900 s); shapes stream back to the parent. A group whose child dies keeps what it delivered and the
  rest is bisected down to the single product, which is left out and listed (`kernel_memory_exceeded`, stats
  kernel_memory_exceeded_total). Opt-out V6_KERNEL_ISOLATE=0.
  - 746974a2 (45 MB): 30,881 parts, 0 missing, peak tree 8.4 GB, 477 s, STEP 1.068 GB; 4efa1dc5 (102 MB): 124,556
    parts, 0 missing, peak 10.0 GB, 540 s, STEP 970 MB. No child died (38 / 76 groups); both keep the two corrupt bolt
    assemblies out (excluded_absurd_coordinates) - class 3 bbox_absurd before.
  - Small models: identical output to 6.1.3.

## 6.1.3

- **OCC lexer crash on names.** OpenCASCADE 8.0.1 segfaults reading a STEP string with an escaped apostrophe followed by
  a comma ('R-O.H.- Rolling:Type OH, 8''x4'', H.M.' - Revit feet-inch names); the grader's whole-file read of 0b3b8b2f
  crashed (rc -11, class 3). Apostrophes in names are now written as the ISO 10303-21 hex escape \X\27, which decodes
  to the same apostrophe (name unchanged; OCC verified). 0b3b8b2f now reads back (class 2: volume outliers, open-source
  surfaces). v5's writer has the same bug (only '''' was handled).
- A part with no read-back result at any level is treated like a reader crash (left out, listed) instead of being kept
  as 'unverified'.
- A double-sided source whose single side is open is a zero-thickness sheet: written as a surface at once (same result,
  no failing solid rounds; 03101a: 10k parts).
- **Exact half-space clipping** (ifc-residue item 3, folded in): ifcopenshell 0.9.0 evaluates some
  IfcBooleanClippingResult chains as a split (the cut-away pieces come back as touching solids); for such products the
  clip is computed exactly with OCC from the same IFC operands when the kernel mesh is not 2-manifold and differs from
  the exact clip. 4bbcc615: parts_without_solid 30 -> 7, other parts unchanged. Opt-out V6_NO_EXACT_CLIP=1; tag
  exact-clip.

## 6.1.2

- **Opening shells with contact walls** (from the IFC volume-residue fixer): SDS/2 countersunk / stepped bolt holes come
  as one IfcFacetedBrep holding cone + cylinder that touch face to face (16 edges used 4x); OCC's boolean with that tool
  returned nothing and the whole plate was lost. Both copies of each such face pair are removed from the opening shell
  in memory (exact union, no face added, source file untouched). 224b42bf: coverage 0.9808 -> 1.0 (28 plates back);
  aa33931d: 0.983 -> 1.0, class 2 -> 1. Opt-out V6_NO_OPENING_REPAIR=1.
- **Composite-curve segments without a ParentCurve** (Tekla 2017i writes `#0`): dropped in memory when a real segment
  remains, so the kernel accepts the profile. e5f30a12: coverage 0.9997 -> 1.0 (2 shear tabs back). Opt-out
  V6_NO_CURVE_REPAIR=1.
- Memory: the 233 GB blow-up on 761b25e0 (L4x3x1/4 angles with holes) is covered by the triangle-mesh path for
  products with openings: peak 1.27 GB, 66 s.

## 6.1.1

- **Every part is read back where it sits.** OCC 8.0.1's validity check depends on the placement: a located copy of a
  valid shared solid can fail (6.1.0-rc verified one instance per shared representation: controls 0933 / 0813 / 0eba59
  had 22 / 50 / 9 invalid instances in the grader's read-back). Verification no longer shares verdicts (opt-in
  V6_VERIFY_DEDUPE=1); a failing instance is rewritten as its own world-coordinate copy (no tag) before any fallback.
  Shared blocks are written once per verification chunk.
- **Memory run-aways contained.** ifcopenshell 0.9.0's polyhedral output can run away on some bodies (Seaport L4 angle
  a3717: > 12 GB in one create_shape, converter at 173 GB; 1.4 MB SDS/2 F35 file: one faceted part, 124 GB):
  products with openings are meshed as triangles (patch E of the verification-residue fixer; coplanar triangles merged
  back into exact polygons), the L2 kernel fallback uses triangle mesh, every fallback regeneration and single-product
  retry runs in a forked child with an address-space cap (VmSize + 12 GB) and a timeout. F35 case: peak 0.52 GB, 10 s.
- **IfcClosedShell in IfcShellBasedSurfaceModel** that the topology finds open is offered to the reader as a solid first
  (like open IfcFacetedBreps); only loose faces (> 50% free edges) go straight to a surface. Open source meshes are not
  filled (owner rule) - they end as tagged surfaces.
- **Corrupt coordinates**: a part reaching 1e10 mm (the grader's absurd-bbox limit; e.g. two Tekla 2022 bolt
  assemblies at -1.7e17 mm in 746974a2 / 4efa1dc5) is left out and listed (`excluded_absurd_coordinates`) instead of
  sending a 124k-part model to class 3.
- **Placement precision** (patch A): MAPPED_ITEM placements with fixed decimals (6.1.0-rc's 10 significant digits
  placed a 3e9 mm instance to the nearest mm).
- **Per-part read-back file** (patch F): `<out>.verify_parts.jsonl.gz` in step_check's --parts format (pid, solids,
  valid, volume) from the converter's own per-part read-back - per-part data for files too large for a whole-file
  read-back. stats `readback_parts` carries the totals.
- Optional far-origin mode (V6_FAR_VERIFY=1, default off; with the grader's translated-read rule): a part beyond 1e7 mm
  that fails only in place is verified on a copy translated by whole km and kept as the exact L0 solid (`far-origin`).
- far_origin_check: parts >= 1e7 mm from the origin can fail OCC's in-place check through floating-point precision
  alone (Baylor 7ff7ad6b part c559_1 at 3e9 mm after triangle meshing); without far mode they take the normal fallback.

## 6.1.0

### Correctness
- **Hole loops of kernel faces (bug in 6.0.1).** ifcopenshell's polyhedral output does not always list the outer loop of
  a face first. 6.0.1 assumed it did, rewound the holes against a hole and produced a mesh whose own volume was wrong
  (OCC read the file correctly, so the per-part volume cross-check failed and the part fell to L2 - correct geometry,
  but tagged). 6.1 takes the loop of largest area as the outer loop. Evidence (5 live L2 parts): 6.1 L0 = 6.0.1 L2 =
  same OCC volume, vertices within 0.008 mm of the exact kernel B-rep, 4x fewer faces than L2.
- **Openings applied to faceted bodies.** v5 / 6.0.1 transcoded IfcFacetedBrep bodies without their IfcOpeningElements
  (bolt holes, copes): 7.7k products in 45 of 67 test files, plates about 5% too heavy. Faceted products with openings
  now go to the kernel, which subtracts the openings (their curvature counts for `approx-curved`).
- **Double-sided meshes** (each face also given reversed, SDS/2 library parts): one copy of each pair is kept; closed
  components are now solids (6.0.1: surface). No component of such a mesh is taken as a void (the winding of the kept
  copies carries no information).
- **Touching bodies in kernel output** are analysed per representation item (a pane in a frame made the pane's faces
  look non-manifold and open).
- **Clearly open source shells** (> 5% free edges: loose quads of grating bars, pipes without end caps) are written as
  surfaces at once (`open-surface`) instead of three failing solid attempts. Genuinely open meshes stay surfaces: no
  hole is filled (owner rule; planar-hole filling awaits the owner's decision).
- A part placing shared geometry that fails verification is first rewritten as its own world-coordinate copy (no tag):
  OCC 8.0.1 BRepCheck fails some located copies of solids that are valid in place.

### Size / speed (read-back cap)
- **Instancing**: a product whose body is one IfcMappedItem of a representation map shared with other such products (no
  openings, rigid transform) places one shared geometry with a MAPPED_ITEM (REPRESENTATION_MAP + AXIS2_PLACEMENT_3D).
  OCC transfers every instance as a located solid; roots = products; per-part volume / validity unchanged. Scaled or
  mirrored placements and products with openings are written as copies. Kernel-made shared geometry is taken from the
  first instance and moved back to the map frame.
- Coplanar adjacent facets of a triangulated shell are merged into polygons with holes (exact; only interior edges go).
- FACE_BOUND for single-loop faces, 9-digit directions.
- Verification: identical parts (same geometry up to translation, or instances of one shared representation) are read
  back once; chunk size adapts to the model; one reader process per chunk, up to max(2, threads, cpu/4) in parallel.
- Results on the three largest Revit test models: 342 MB IFC -> 683 MB STEP (v5 3398 MB), 339 MB -> 781 MB (v5 3474 MB),
  298 MB -> 455 MB (v5 3069 MB), 269 MB IFC2X2 -> 764 MB (v5 2995 MB); 6-9 min each (6.0.1: 45 min). The live
  not-read-back models are 35/40 SDS/2 and 5/40 Revit, all MappedRepresentation-heavy.

### Output layout (for streamed verifiers)
Header globals #101-#117 (contexts, units, origin, axis directions) first, then the shared representation blocks, then
one contiguous block per part ending with its SHAPE_DEFINITION_REPRESENTATION; a part block references only the header
block, its own entities and at most one shared block (its REPRESENTATION_MAP).

### Tags
stats.json `tags` now uses the description names (`L1-triangulated`, `L2-alt-source`, `L3-partial-surface`,
`L4-surface`, `approx-curved`, `open-surface`, `unverified`) plus info tags (`instanced`, `double-sided`, `sewn`,
`tjunction`, `components`, `reoriented`, `void`). L2 = the same IFC item re-faceted (approved as exact when it verifies).

## 6.0.1 (shipped first: orientation + invalid-solid healing)

Topology repair per source shell (never adds a face, never moves a vertex by more than the seam tolerance):
- vertices welded on the output grid (10^-prec mm); repeated points, zero-area loops / faces removed
- **multi-lump shells split**: one IfcClosedShell holding several bodies (bolt + nut + washers, grating bars, weld
  runs) -> one FACETED_BREP per edge-connected component. This was the main cause of `non_positive_volume_solids`.
- **contact walls removed**: two bodies touching face to face exported in one shell carry the shared face twice with
  opposite winding -> both copies dropped, the bodies merge into their exact union.
- **orientation**: faces made consistent per component, every component outward (signed volume); a component enclosed
  by another and wound opposite to it in the source is a void (BREP_WITH_VOIDS); IfcFacetedBrepWithVoids voids written
  as voids (v5 wrote them as extra positive solids).
- hole loops wound against their outer loop; non-planar polygons split into triangles on their own vertices; pinched
  loops split; T-junctions split; tessellation seams closed by merging boundary vertices < 0.1 mm apart (prec 2).
- kernel path with polyhedral output (planar faces = exact polygons with holes), streamed product by product; products
  the iterator skips are retried one by one.
- **verification + fallback chain** per part with the grader's checks (OCC read, BRepCheck, volume > 0, faces, finite
  bbox, OCC volume vs mesh volume 2%): L1 triangulated -> L2 other source -> L3 valid solids + failing solids as open
  shells -> L4 surface model; a part whose every form crashes the reader is left out and listed.
- tagging: PRODUCT.description `<IfcClass> [v6:<tags>]`, sidecar `<out>.parts.json`, counts in stats.json.
- body representation Body > Facetation > unnamed (v5 summed them); IfcPolygonalFaceSet inner loops + PnIndex;
  corrupt coordinates -> kernel; heartbeat every 120 s (worker stall kill after 30 min of silence).
- input: ifcZIP / gzip, legacy schema labels -> IFC2X3, IFC4X1..IFC4X3_* -> IFC4X3_ADD2, IFC4 RC/ADD -> IFC4, schema by
  entity names when the label does not parse, Windows NaN tokens, trailing garbage, lossless tail repair, built-in
  ifcXML -> SPF reader (the dedicated ifcxml2spf workflow owns that path).
