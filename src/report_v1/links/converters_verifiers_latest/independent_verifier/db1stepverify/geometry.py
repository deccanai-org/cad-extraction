"""Per-part STEP geometry in OpenCascade (what a user of the dataset will load), plus a triangle soup for rendering.
Deterministic: every part is measured; BRepCheck on every part up to BREPCHECK_ALL_MAX, above that every k-th."""
import numpy as np
from . import config as C


def analyze_step(path, want_mesh=True, max_tris=6_000_000):
    from OCP.STEPControl import STEPControl_Reader
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_SOLID, TopAbs_SHELL, TopAbs_FACE, TopAbs_REVERSED
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRep import BRep_Tool
    from OCP.TopoDS import TopoDS
    from OCP.TopLoc import TopLoc_Location
    from OCP.BRepMesh import BRepMesh_IncrementalMesh

    _face = getattr(TopoDS, "Face_s", None) or TopoDS.Face        # static-method name differs across OCP builds
    rd = STEPControl_Reader()
    if rd.ReadFile(path) != IFSelect_RetDone:
        return dict(error="OpenCascade could not read the file")
    nr = rd.NbRootsForTransfer()
    stride = 1 if nr <= C.BREPCHECK_ALL_MAX else -(-nr // C.BREPCHECK_ALL_MAX)
    parts = []; shapes = []

    def count(s, t):
        e = TopExp_Explorer(s, t); n = 0
        while e.More(): n += 1; e.Next()
        return n

    for i in range(1, nr + 1):
        rd.ClearShapes(); ok = rd.TransferRoot(i); s = rd.OneShape()
        p = dict(part=i)
        if not ok or s.IsNull(): p["kind"] = "empty"; parts.append(p); continue
        b = Bnd_Box(); BRepBndLib.Add_s(s, b, False)
        if b.IsVoid(): p["kind"] = "empty"; parts.append(p); continue
        mn, mx = b.CornerMin(), b.CornerMax()
        p["bbox"] = [mn.X(), mn.Y(), mn.Z(), mx.X(), mx.Y(), mx.Z()]
        box = max(0.0, mx.X() - mn.X()) * max(0.0, mx.Y() - mn.Y()) * max(0.0, mx.Z() - mn.Z())
        ns = count(s, TopAbs_SOLID); p["solids"] = ns; p["faces"] = count(s, TopAbs_FACE)
        if ns == 0:
            p["kind"] = "no_solid"
        else:
            g = GProp_GProps(); BRepGProp.VolumeProperties_s(s, g); v = g.Mass(); c = g.CentreOfMass()
            p["volume_mm3"] = abs(v); p["signed_volume_mm3"] = v; p["centroid"] = [c.X(), c.Y(), c.Z()]
            p["kind"] = ("impossible_solid" if abs(v) > box * C.VOLUME_BOX_FACTOR + 1e-6 else
                         "inverted_solid" if v < 0 else "degenerate_solid" if abs(v) < C.TINY_VOLUME_MM3 else "solid")
            if (i - 1) % stride == 0: p["brep_valid"] = bool(BRepCheck_Analyzer(s).IsValid())
        if "centroid" not in p:
            p["centroid"] = [(p["bbox"][k] + p["bbox"][k + 3]) / 2 for k in range(3)]
        if want_mesh: shapes.append((i - 1, s))
        parts.append(p)
    T, O, complete = (_mesh_stl(shapes, path, max_tris) if want_mesh and shapes else (np.zeros((0, 3, 3)), np.zeros(0, np.int64), True))
    return dict(parts=parts, roots=nr, brepcheck_stride=stride, tris=T, tri_part=O, mesh_complete=complete)


def _mesh_stl(shapes, path, max_tris):
    """Mesh all parts in one compound (OpenCascade, parallel), write one binary STL in C++, read it with numpy.
    Part ownership: the STL writer walks faces in compound order, so each part's triangles are consecutive; counts
    per part come from the face triangulations. ~50x faster than reading nodes one by one from Python."""
    import os, tempfile
    from OCP.TopoDS import TopoDS_Compound
    from OCP.BRep import BRep_Builder, BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.StlAPI import StlAPI_Writer
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS
    _face = getattr(TopoDS, "Face_s", None) or TopoDS.Face
    nf = sum(1 for _ in shapes)
    step = 1
    comp = TopoDS_Compound(); bb = BRep_Builder(); bb.MakeCompound(comp)
    for k, (i, s) in enumerate(shapes):
        if k % step == 0: bb.Add(comp, s)
    BRepMesh_IncrementalMesh(comp, 2.0, False, 0.5, True)
    own = []
    for k, (i, s) in enumerate(shapes):
        if k % step: continue
        n = 0; e = TopExp_Explorer(s, TopAbs_FACE)
        while e.More():
            t = BRep_Tool.Triangulation_s(_face(e.Current()), TopLoc_Location())
            if t is not None: n += t.NbTriangles()
            e.Next()
        own.append(np.full(n, i, np.int64))
    O = np.concatenate(own) if own else np.zeros(0, np.int64)
    fd, tmp = tempfile.mkstemp(suffix=".stl", dir=os.path.dirname(os.path.abspath(path))); os.close(fd)
    try:
        w = StlAPI_Writer()
        try: w.ASCIIMode = False
        except Exception: pass
        w.Write(comp, tmp)
        raw = open(tmp, "rb").read()
    finally:
        os.remove(tmp)
    n = int(np.frombuffer(raw, np.uint32, 1, 80)[0]) if len(raw) >= 84 and raw[:5] != b"solid" else -1
    if n < 0 or len(raw) != 84 + 50 * n:
        return np.zeros((0, 3, 3)), np.zeros(0, np.int64), False
    rec = np.frombuffer(raw, np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]), n, 84)
    T = rec["v"].astype(np.float64)
    if len(O) != n: O = np.full(n, -1, np.int64)          # ownership unknown: render still works, colouring by part does not
    if n > max_tris:
        sel = np.arange(0, n, -(-n // max_tris)); T, O = T[sel], O[sel]
    return T, O, len(O) == 0 or O[0] >= 0


def _strays(Cn):
    """Parts cut off from the model: centroids are linked when closer than a gap r (the larger of STRAY_MIN_GAP_MM and
    OUTLIER_FACTOR x the model's 95th-percentile 3rd-neighbour spacing), via an occupancy grid of cell size r and
    26-neighbour union-find. A part is a stray when its cluster holds <= max(1, min(50, 1%)) of the parts.
    Distribution-free: long racks, towers, skewed layouts and single details are all handled."""
    n = len(Cn)
    if n < 3: return np.zeros(n, bool)
    from scipy.spatial import cKDTree
    k = min(4, n); kd, _ = cKDTree(Cn).query(Cn, k=k)
    r = max(C.STRAY_MIN_GAP_MM, C.OUTLIER_FACTOR * float(np.percentile(kd[:, k - 1], 75)))   # 75th: strays must not set the scale
    cell = np.floor(Cn / r).astype(np.int64)
    keys, inv = np.unique(cell, axis=0, return_inverse=True); inv = inv.ravel()
    idx = {tuple(c): i for i, c in enumerate(keys)}
    par = list(range(len(keys)))
    def find(a):
        while par[a] != a: par[a] = par[par[a]]; a = par[a]
        return a
    offs = [(dx, dy, dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1) if (dx, dy, dz) > (0, 0, 0)]
    for i, c in enumerate(keys):
        for o in offs:
            j = idx.get((c[0] + o[0], c[1] + o[1], c[2] + o[2]))
            if j is not None:
                a, b = find(i), find(j)
                if a != b: par[a] = b
    root = np.array([find(i) for i in range(len(keys))])[inv]
    _, rinv, cnt = np.unique(root, return_inverse=True, return_counts=True)
    return cnt[rinv.ravel()] <= max(1, min(50, int(0.01 * n)))


def summarize(geo, names=None):
    """Model-level checks on the part list: counts by kind, extent, strays, duplicates, BRepCheck."""
    parts = geo["parts"]
    kinds = {}
    for p in parts: kinds[p["kind"]] = kinds.get(p["kind"], 0) + 1
    good = [p for p in parts if "bbox" in p]
    S = dict(parts=len(parts), kinds=kinds)
    if not good:
        S.update(extent_mm=[0, 0, 0]); return S
    B = np.array([p["bbox"] for p in good]); lo, hi = B[:, :3].min(0), B[:, 3:].max(0)
    S["extent_mm"] = [float(x) for x in hi - lo]
    S["bbox_mm"] = [float(x) for x in (*lo, *hi)]
    Cn = np.array([p["centroid"] for p in good])
    stray = _strays(Cn)
    core = Cn[~stray] if (~stray).any() else Cn
    lo_c, hi_c = np.percentile(core, 1, axis=0), np.percentile(core, 99, axis=0)
    S["stray_parts"] = int(stray.sum()); S["stray_share"] = float(stray.mean())
    S["stray_examples"] = [dict(part=good[i]["part"], centroid=[round(x, 1) for x in good[i]["centroid"]],
                                name=(names[good[i]["part"] - 1] if names and len(names) >= good[i]["part"] else None))
                           for i in np.flatnonzero(stray)[:10]]
    S["core_extent_mm"] = [float(x) for x in hi_c - lo_c]
    sol = [p for p in good if "volume_mm3" in p]
    key = {}
    for p in sol:
        k = tuple(np.round(p["centroid"], 1)) + (round(p["volume_mm3"], -1),)
        key[k] = key.get(k, 0) + 1
    dup = sum(n - 1 for n in key.values() if n > 1)
    S["coincident_duplicates"] = dup; S["duplicate_share"] = dup / max(1, len(sol))
    S["volume_m3"] = float(sum(p["volume_mm3"] for p in sol if p["kind"] == "solid")) / 1e9
    chk = [p for p in parts if "brep_valid" in p]
    S["brepcheck_checked"] = len(chk); S["brepcheck_invalid"] = sum(not p["brep_valid"] for p in chk)
    S["brepcheck_stride"] = geo.get("brepcheck_stride")
    return S
