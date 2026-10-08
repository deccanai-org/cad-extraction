# ifc2step6 changes (vs ifc2step5)

Drop-in: same CLI (`IN OUT --mode hybrid|transcode|tess --threads N --prec N [--nodedup --noplane --gzip]`), same flavour
(AUTOMOTIVE_DESIGN, FACETED_BREP / POLY_LOOP, no ADVANCED_FACE / tessellated entities), same PRODUCT mapping
(id = GlobalId, name = Name, description = IFC class), same `<out>.stats.json` + stats JSON on stdout. Runs on the kit env
(ifcopenshell 0.9.0 + pythonocc 8.0.1); under the 0.8.4 venv it finds `../env/bin/python` for verification.

## 6.0.1 (shipped first: orientation + invalid-solid healing)

Topology repair per source shell (never adds a face, never moves a vertex by more than the seam tolerance):
- vertices welded on the output grid (10^-prec mm); repeated points, zero-area loops / faces removed
- **multi-lump shells split**: one IfcClosedShell holding several bodies (bolt + nut + washers, grating bars, weld
  runs) -> one FACETED_BREP per edge-connected component. This was the main cause of `non_positive_volume_solids`
  (OCC's reader turned such shells into solids with an inner shell -> negative volume).
- **contact walls removed**: two bodies touching face to face exported in one shell (bolt head on shank) carry the
  shared face twice with opposite winding -> both copies dropped, the bodies merge into their exact union.
- **orientation**: faces made consistent per component (walk over manifold edges), every component outward (signed
  volume); a component enclosed by another and wound opposite to it in the source is a void (BREP_WITH_VOIDS);
  IfcFacetedBrepWithVoids voids written as voids (v5 wrote them as extra positive solids).
- **hole loops** wound against their outer loop (SDS/2 HSS / plate holes came wound like the outer loop).
- **non-planar polygons** split into triangles on their own vertices (ear clipping, holes bridged).
- **pinched loops** (a vertex visited twice) split into simple loops.
- **T-junctions** split (vertex already on the edge); **tessellation seams** closed by merging boundary vertices
  < 0.1 mm apart (prec 2), kept only if open edges decrease.
- **double-sided surfaces** (every face also given reversed, zero thickness; SDS/2 `PartLibFastener`) written once as a
  surface model, tagged `open-surface` - not offered as a solid.
- a part whose faces all fall out in repair keeps its cleaned source faces as a surface (never dropped).

Kernel path (everything not faceted): ifcopenshell polyhedral output (`POLYHEDRON_WITH_HOLES`): planar faces come out as
exact polygons with holes instead of triangles (fewer faces, smaller files), streamed product by product.
Products the iterator skips are retried one by one (polyhedral, then triangle mesh).

**Verification + fallback chain (per part, same checks as step_check):** every part is read back with OpenCASCADE in
small chunk files, one reader process per chunk (OCC 8.0.1 segfaults reading a second large STEP in one process),
`--verify-procs` in parallel: transfer, solids, BRepCheck_Analyzer, volume > 0, faces, finite bbox, OCC volume vs mesh
volume (2%). A failing part goes down: L1 every face triangulated -> L2 other source (transcode <-> kernel, kernel
polyhedral -> triangle mesh) -> L3 valid solids kept + failing solids as open shells -> L4 whole part as surface model.
A part whose every representation crashes the reader is left out and listed (`dropped_reader_crash`).

**Tagging** (owner rule: exact vs approximate visible per part): PRODUCT.description = `<IfcClass> [v6:<tags>]` for
`approx-curved` (kernel facets of curved source geometry), `L1-triangulated`, `L2-alt-source`, `L3-partial-surface`,
`L4-surface`, `open-surface`, `unverified`. Sidecar `<out>.parts.json` (every part: gid, class, source, level, tags,
solids, surface models, faces, mesh volume, fallback history); stats.json carries counts (`levels`, `tags`, `repair`,
`exact_parts`, `approx_parts`, `surface_fallback_parts`) and the tagged-part list (`tagged_parts`, capped at 5000).

Other: body representation chosen Body > Facetation > unnamed (v5 summed them: double geometry when both exist);
IfcPolygonalFaceSet inner loops and PnIndex honoured (v5 ignored both); corrupt coordinates (non-finite / > 1e13 mm)
route the product to the kernel (guard logic built in, so `ifc2step6_guard.py` = same file); placement that cannot be
evaluated routes to the kernel instead of identity; AXIS2_PLACEMENT_3D without ref direction and planes shared per part
(smaller files); heartbeat line every 120 s (the worker kills a converter whose log is silent for 30 min).

Input: ifcZIP / gzip unpacked, legacy schema labels (IFC2X2_FINAL, IFC2X_FINAL, ...) -> IFC2X3, IFC4X1..IFC4X3_* ->
IFC4X3_ADD2, IFC4 RC/ADD variants -> IFC4, a label that does not parse -> schema chosen by entity names, Windows NaN
tokens zeroed, text after END-ISO-10303-21 dropped, a truncated tail repaired only with 0 dangling references.
(ifcXML: a built-in reader exists in this file; the dedicated ifcxml2spf workflow owns that path.)

Known limits (v6.1 work): STEP size of the very largest models (258 MB IFC -> 1.10 GB, over the 1 GB read-back cap;
v5 2.0 GB): coplanar merge of triangulated source facets next; grader expectation bugs for volumes (see report).
