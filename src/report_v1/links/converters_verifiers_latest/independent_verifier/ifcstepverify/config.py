"""Every rule constant in one place. Changing any of these changes RULES_VERSION."""
RULES_VERSION = "2026.09.28-1"

# IFC element types the converters skip on purpose (ifc2step SKIP_TYPES + IfcConvert defaults)
SKIP_TYPES = frozenset({"IfcOpeningElement", "IfcOpeningStandardCase", "IfcSpace", "IfcGrid", "IfcAnnotation", "IfcVirtualElement"})
# not physical parts: never expected in the STEP
NONPHYS = SKIP_TYPES | frozenset({"IfcSite", "IfcBuilding", "IfcBuildingStorey", "IfcProject", "IfcSpatialZone", "IfcGridAxis"})
BODY_IDS = (None, "Body", "Facetation")            # representation identifiers ifc2step reads
SURFACE_ITEMS = frozenset({"IfcShellBasedSurfaceModel", "IfcFaceBasedSurfaceModel", "IfcOpenShell"})
FACETED_ITEMS = frozenset({"IfcFacetedBrep", "IfcFacetedBrepWithVoids"})
TRANSCODE_ITEMS = FACETED_ITEMS | SURFACE_ITEMS | frozenset({"IfcPolygonalFaceSet", "IfcTriangulatedFaceSet"})

# writers recognised from the STEP header
IFC_WRITERS = ("ifc2step", "ifcconvert_occ")

# tolerances
VOLUME_BOX_FACTOR = 1.001          # a solid's volume may not exceed its own bounding box by more than this
BBOX_RATIO_TOL = 0.01              # overall STEP size vs IFC size, per axis
VOLUME_RATIO_TOL = 0.05            # total solid volume vs IFC, both without impossible elements
NAME_MATCH_MIN = 0.90              # below: source match is weak
BREPCHECK_WARN_SHARE = 0.01        # share of solids failing BRepCheck that makes it a warning
POINT_ROUND = 6                    # decimals when testing IFC B-rep watertightness

# determinism
SEED = 20260928
BREPCHECK_ALL_MAX = 250_000        # check every solid up to this many parts; above, every k-th part (deterministic)
FLOAT_DIGITS = 6                   # significant digits in outputs

# resource defaults (override on the command line / environment)
STEP_GEOM_MAX_BYTES = 2e9          # STEP files larger than this get integrity + matching only (reported, never silent)
IFC_GEOM_MAX_BYTES = 1e9
CANDIDATE_BATCH = 4                # candidate IFCs scored per batch (early stop only between batches -> deterministic)
