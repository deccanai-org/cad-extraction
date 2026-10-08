"""Every rule constant in one place. Changing any of these changes RULES_VERSION."""
RULES_VERSION = "2026.09.29-1"

# where things live
BUCKET = "annotationprod"
REGION = "ap-south-1"
ROOT = "cad-disk-extract"
STEP_PREFIX = f"{ROOT}/conversions/db1-step/"
RESULTS_PREFIX = f"{ROOT}/_state/db1-v2/results/"
CTL_PREFIX = f"{ROOT}/_control/db1-v2/"
SRC_BUCKET = "bim-proprietary-data"          # original disk images: the fallback when an input .db1 is gone
CURRENT_CODE = "db1-2026-09-25g"              # converter code version of the production run

# the converter's output contract (db1_worker.py): AP214 faceted B-rep, one closed solid per part
REQUIRED_SCHEMA = "AUTOMOTIVE_DESIGN"
FORBIDDEN_ENTITIES = ("ADVANCED_FACE", "TESSELLATED_SOLID", "TESSELLATED_SHELL", "TRIANGULATED_FACE_SET")
WRITER_TAG = "ifc2step"

# geometry sanity
VOLUME_BOX_FACTOR = 1.001        # a solid's volume may not exceed its own bounding box by more than this
MAX_MODEL_EXTENT_MM = 3.0e6      # 3 km: anything larger is a decoding error (Tekla models are building-sized)
OUTLIER_FACTOR = 10.0            # stray: 3rd-nearest-neighbour gap this many times the model's 95th-percentile gap
STRAY_MIN_GAP_MM = 20_000.0      # ... and at least 20 m from its neighbours
FAR_STRAY_MM = 1_000_000.0       # a stray that stretches the model beyond 1 km ...
FAR_STRAY_FACTOR = 10.0          # ... and to 10x the model's own size is a corrupted position (always a warning)
OUTLIER_SHARE_WARN = 0.005       # share of stray parts that makes a warning
TINY_VOLUME_MM3 = 1.0            # solids below 1 mm3 are degenerate
DUP_SHARE_WARN = 0.05            # share of exactly coincident parts (same centroid + volume) that makes a warning
BREPCHECK_ALL_MAX = 60_000       # check every solid up to this many parts; above, every k-th (deterministic)
BREPCHECK_WARN_SHARE = 0.01

# decoder coverage: members per MB of decompressed model (fleet of 8,837: median 233/MB for models >= 20 MB, 1st pct 1.2)
SPARSE_MIN_MB = 20.0
SPARSE_MEMBERS_PER_MB = 5.0

# reproduction (re-run the production decoder on the input)
REPRO_CENTROID_TOL_MM = 1.0      # --prec 2 rounds to 0.01 mm; tessellation moves centroids of curved sections slightly
REPRO_VOLUME_TOL = 0.03
REPRO_MATCH_MIN = 0.98           # share of STEP parts reproduced from the input for a pass

# ground truth (Tekla's own IFC export found next to the .db1)
TRUTH_TYPES = ("IfcBeam", "IfcColumn", "IfcMember", "IfcPlate", "IfcFooting", "IfcSlab", "IfcWall",
               "IfcBuildingElementProxy", "IfcRailing", "IfcStair", "IfcStairFlight", "IfcRamp", "IfcPile")
TRUTH_EXCLUDED = ("IfcMechanicalFastener", "IfcDiscreteAccessory", "IfcFastener", "IfcReinforcingBar",
                  "IfcReinforcingMesh", "IfcTendon", "IfcElementAssembly")   # bolts/rebar: not converted by design
TRUTH_IFC_MAX_BYTES = 400e6
TRUTH_MESH_TIMEOUT_S = 900       # IfcOpenShell can loop forever on some boolean cuts: give up and say so
TRUTH_MATCH_DIST_MM = 10.0       # centroid distance after alignment
TRUTH_MATCH_VOL_TOL = 0.10       # Tekla fittings/chamfers move volumes a little
TRUTH_NEAR_DIST_MM = 60.0
TRUTH_RECALL_PASS = 0.90         # share of IFC elements found in the STEP
TRUTH_RECALL_WARN = 0.60
TRUTH_PRECISION_MIN = 0.50       # share of STEP parts inside the IFC's extent that match an IFC element
TRUTH_ALIGN_MIN_VOTES = 8
NAME_OVERLAP_MIN = 0.50          # profile-name multiset overlap that says "same model" regardless of placement

# render + VLM
RENDER_POINTS = 2_500_000
RENDER_W, RENDER_H = 800, 600
VLM_MODEL = "claude-opus-5-5"
VLM_EFFORT = "high"

# determinism
SEED = 20260929
FLOAT_DIGITS = 6

# local resource limits (a laptop run; EC2 raises them)
STEP_GEOM_MAX_BYTES = 400e6
DB1_REPRO_MAX_BYTES = 60e6
