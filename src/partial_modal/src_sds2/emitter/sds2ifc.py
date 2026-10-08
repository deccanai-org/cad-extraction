"""IFC4 emitter for the SDS/2 -> STEP converter (sds2-step-pipeline v4 / v5.x), version-agnostic.

The converter builds every solid it writes in an XCAF document and hands that document to STEPCAFControl_Writer. This
module hooks three points of the converter process (install()), without changing what the converter computes or writes:

  brep.cut_holes(sh, H)             records result -> (uncut solid, the hole tools exactly as cut_holes builds them:
                                    round = cylinder of radius dia/2 from c - 0.05 in along -axis over depth + 0.1 in;
                                    slotted = the obround prism of the same lines and arcs)
  OCP BRepBuilderAPI_Transform      records placed copy -> (source shape, 3x4 transform)
  to_step2.STEPCAFControl_Writer    on Write() of the converter's final STEP (the -o path), walks the same document the
                                    STEP writer just wrote and emits <out>.ifc from it

So the IFC holds exactly the shapes of the STEP: every top-level instance (an assembly component of a shared part, or a
placed copy) becomes one IFC product named by its STEP label, placed by the same transform, its geometry the part's own:
  - a solid whose faces are all planar polygons (SDS/2's faceted piece B-rep after the converter's repair, bolt hexes,
    concrete prisms, member envelopes): IfcFacetedBrep (vertices at full double precision, loops oriented outward)
  - a right circular cylinder (rods, studs, bolt shanks): IfcExtrudedAreaSolid of an IfcCircleProfileDef
  - a solid the converter cut holes into: IfcBooleanResult DIFFERENCE chain, first operand the uncut solid as above,
    second operands the hole tools as IfcExtrudedAreaSolid (IfcCircleProfileDef, or an obround IfcIndexedPolyCurve
    profile for slots) - the same cylinders / prisms cut_holes subtracted
  - an open surface (SDS/2 stored faces that do not close): IfcShellBasedSurfaceModel
Anything else is reported (unsupported) and the model is not emitted as complete.
One IfcElementAssembly per SDS/2 member ('<type> #<member>'); GlobalIds derive from the shipped STEP's sha256 and the
instance label (sds2label.guid), so the delivered STEP reader of the pipeline finds every product again.
"""
import collections, hashlib, json, math, os, re, sys, time, traceback
import numpy as np

EMITTER = 'z3-sds2-ifc-emitter'
EMITTER_VERSION = '1.1'
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sds2label  # noqa: E402

TARGET = None
META = {}
_CUT = None          # TopTools_IndexedMapOfShape of cut results
_CUT_INFO = {}
_TRN = None          # placed copies
_TRN_INFO = {}
_MM = 25.4


# ======================================================================================== hooks
def _shape_map():
    """an indexed map of shapes keyed as TopoDS_Shape::IsSame (same TShape and location), OCP version safe"""
    try:
        from OCP.TopTools import TopTools_IndexedMapOfShape
        return TopTools_IndexedMapOfShape()
    except ImportError:
        from OCP.collections import IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher
        return IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher()


def install(conv_root, target, meta):
    global TARGET, META, _CUT, _TRN, _MM
    TARGET = os.path.abspath(target)
    META = dict(meta)
    sys.path.insert(0, os.path.join(conv_root, 'decode'))
    import OCP.BRepBuilderAPI as BB
    from OCP.TopoDS import TopoDS_Shape
    from OCP.gp import gp_Trsf
    _CUT = _shape_map()
    _TRN = _shape_map()
    import brep
    _MM = float(getattr(brep, 'MM', 25.4))
    orig_cut = brep.cut_holes

    def cut_holes(sh, H):
        res = orig_cut(sh, H)
        try:
            if res is not None and res is not sh and not res.IsSame(sh):
                tools = [t for t in (_tool_of(h) for h in (H or [])) if t is not None]
                i = _CUT.Add(res)
                _CUT_INFO[i] = (sh, tools)
        except Exception:
            META.setdefault('hook_errors', []).append('cut_holes: ' + traceback.format_exc(limit=2))
        return res
    brep.cut_holes = cut_holes
    Orig = BB.BRepBuilderAPI_Transform

    class _Transform(Orig):
        def __init__(self, *a):
            super().__init__(*a)
            try:
                if len(a) >= 2 and isinstance(a[0], TopoDS_Shape) and isinstance(a[1], gp_Trsf):
                    res = self.Shape()
                    t = a[1]
                    M = np.array([[t.Value(r, c) for c in (1, 2, 3, 4)] for r in (1, 2, 3)], float)
                    i = _TRN.Add(res)
                    _TRN_INFO[i] = (a[0], M)
            except Exception:
                META.setdefault('hook_errors', []).append('transform: ' + traceback.format_exc(limit=2))
    BB.BRepBuilderAPI_Transform = _Transform
    import to_step2
    OrigW = to_step2.STEPCAFControl_Writer

    class _Writer:
        def __init__(self, *a):
            self._w = OrigW(*a)
            self._doc = None

        def Transfer(self, doc, *a):
            self._doc = doc
            return self._w.Transfer(doc, *a)

        def Write(self, path):
            r = self._w.Write(path)
            if os.path.abspath(path) == TARGET and self._doc is not None:
                try:
                    emit(self._doc, path)
                except Exception:
                    err = traceback.format_exc()
                    open(os.path.splitext(path)[0] + '_ifc_error.txt', 'w').write(err)
                    print('IFC emitter error:', err[-2000:])
            return r

        def __getattr__(self, k):
            return getattr(self._w, k)
    to_step2.STEPCAFControl_Writer = _Writer


def _tool_of(h):
    """the hole tool exactly as brep.cut_holes builds it (same arithmetic; None where cut_holes' construction fails)"""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakePrism
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire, BRepBuilderAPI_MakeFace
    from OCP.GC import GC_MakeArcOfCircle, GC_MakeSegment
    from OCP.gp import gp_Pnt, gp_Ax2, gp_Dir, gp_Vec
    MM = _MM
    with np.errstate(all='ignore'):
        a = -np.asarray(h["axis"], float); a /= np.linalg.norm(a)
        p0 = (h["c"] - a * 0.05) * MM
        L = (h["depth"] + 0.1) * MM; r = h["dia"] / 2 * MM
    try:
        if h["slot"] <= 0:
            BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*p0), gp_Dir(*a)), r, L).Shape()
            return dict(kind='circle', p0=[float(x) for x in p0], a=[float(x) for x in a], L=float(L), r=float(r))
        d = np.cos(h["ang"]) * h["R"][0] + np.sin(h["ang"]) * h["R"][1]
        d = d - a * (d @ a); d /= np.linalg.norm(d); n = np.cross(a, d)
        s = h["slot"] / 2 * MM
        P = lambda u, v: gp_Pnt(*(p0 + d * u + n * v))
        e = [GC_MakeSegment(P(-s, -r), P(s, -r)).Value(), GC_MakeArcOfCircle(P(s, -r), P(s + r, 0), P(s, r)).Value(),
             GC_MakeSegment(P(s, r), P(-s, r)).Value(), GC_MakeArcOfCircle(P(-s, r), P(-s - r, 0), P(-s, -r)).Value()]
        w = BRepBuilderAPI_MakeWire()
        for c in e:
            w.Add(BRepBuilderAPI_MakeEdge(c).Edge())
        BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(w.Wire()).Face(), gp_Vec(*(a * L))).Shape()
        return dict(kind='slot', p0=[float(x) for x in p0], a=[float(x) for x in a], d=[float(x) for x in d],
                    L=float(L), r=float(r), s=float(s))
    except Exception:
        return None


# ======================================================================================== STEP / IFC text
def _real(x):
    x = float(x)
    if not math.isfinite(x):
        raise ValueError('non-finite coordinate')
    if x == 0.0:
        return '0.'
    s = repr(x)
    if 'e' in s or 'E' in s:
        m, e = s.lower().split('e')
        if '.' not in m:
            m += '.'
        return m + 'E' + e
    return s if '.' in s else s + '.'


def _str(s):
    if s is None:
        return '$'
    out = []
    for ch in str(s):
        o = ord(ch)
        if ch == "'":
            out.append("''")
        elif ch == '\\':
            out.append('\\\\')
        elif 32 <= o < 127:
            out.append(ch)
        elif o < 0x10000:
            out.append('\\X2\\%04X\\X0\\' % o)
        else:
            out.append('\\X4\\%08X\\X0\\' % o)
    return "'" + ''.join(out) + "'"


class _File:
    def __init__(self):
        self.lines = []
        self.n = 0

    def add(self, text):
        self.n += 1
        self.lines.append('#%d=%s;' % (self.n, text))
        return '#%d' % self.n


def _tup(refs):
    return '(' + ','.join(refs) + ')'


# ======================================================================================== geometry decomposition
class Unsupported(Exception):
    pass


def _children(shape, kind, avoid=None):
    from OCP.TopExp import TopExp_Explorer
    ex = TopExp_Explorer(shape, kind, avoid) if avoid is not None else TopExp_Explorer(shape, kind)
    out = []
    while ex.More():
        out.append(ex.Current())
        ex.Next()
    return out


def _cast(name, s):
    from OCP.TopoDS import TopoDS
    f = getattr(TopoDS, name + '_s', None) or getattr(TopoDS, name)
    return f(s)


def _pnt(v):
    from OCP.BRep import BRep_Tool
    p = BRep_Tool.Pnt_s(_cast('Vertex', v))
    return (p.X(), p.Y(), p.Z())


def _newell(P):
    P = np.asarray(P, float)
    q = np.roll(P, -1, axis=0)
    return np.array([np.sum((P[:, 1] - q[:, 1]) * (P[:, 2] + q[:, 2])), np.sum((P[:, 2] - q[:, 2]) * (P[:, 0] + q[:, 0])),
                     np.sum((P[:, 0] - q[:, 0]) * (P[:, 1] + q[:, 1]))])


def _face_loops(face):
    """planar face with straight edges -> [outer loop, inner loops...] of points, outer counter-clockwise and inner
    clockwise about the face's outward normal (the face orientation applied); Unsupported for any other face"""
    from OCP.BRepAdaptor import BRepAdaptor_Surface, BRepAdaptor_Curve
    from OCP.GeomAbs import GeomAbs_Plane, GeomAbs_Line
    from OCP.BRepTools import BRepTools, BRepTools_WireExplorer
    from OCP.TopAbs import TopAbs_WIRE, TopAbs_REVERSED
    from OCP.TopoDS import TopoDS
    f = _cast('Face', face)
    ad = BRepAdaptor_Surface(f)
    if ad.GetType() != GeomAbs_Plane:
        raise Unsupported('face surface type %s' % str(ad.GetType()))
    ax = ad.Plane().Axis().Direction()
    nrm = np.array([ax.X(), ax.Y(), ax.Z()])
    if f.Orientation() == TopAbs_REVERSED:
        nrm = -nrm
    outer = BRepTools.OuterWire_s(f)
    loops = []
    for w in _children(f, TopAbs_WIRE):
        w = _cast('Wire', w)
        we = BRepTools_WireExplorer(w, f)
        pts = []
        while we.More():
            e = we.Current()
            if BRepAdaptor_Curve(e).GetType() != GeomAbs_Line:
                raise Unsupported('curved edge on a planar face')
            pts.append(_pnt(we.CurrentVertex()))
            we.Next()
        pts = [p for i, p in enumerate(pts) if i == 0 or p != pts[i - 1]]
        while len(pts) > 1 and pts[-1] == pts[0]:
            pts.pop()
        if len(pts) < 3:
            raise Unsupported('degenerate face loop')
        is_outer = w.IsSame(outer)
        sgn = float(np.dot(_newell(pts), nrm))
        if (is_outer and sgn < 0) or (not is_outer and sgn > 0):
            pts = pts[::-1]
        loops.append((0 if is_outer else 1, pts))
    if not loops or sum(1 for k, _ in loops if k == 0) != 1:
        raise Unsupported('face without one outer wire')
    loops.sort(key=lambda x: x[0])
    return [p for _, p in loops]


SPIKE_COS = -0.95      # a loop vertex where the boundary turns back by more than ~162 degrees


def _spike(loop):
    P = np.asarray(loop, float)
    d1 = P - np.roll(P, 1, axis=0)
    d2 = np.roll(P, -1, axis=0) - P
    c = np.einsum('ij,ij->i', d1, d2) / (np.linalg.norm(d1, axis=1) * np.linalg.norm(d2, axis=1))
    return bool(np.any(c < SPIKE_COS))


def _ear_clip(loop):
    """triangles (index triples, same orientation) of a simple planar polygon by ear clipping in its own plane; None
    when no ear is found (collinear runs, touching boundary): the face is then written as it is"""
    P = np.asarray(loop, float)
    n = _newell(P)
    n = n / np.linalg.norm(n)
    u = P[1] - P[0]
    u = u - n * (u @ n)
    u = u / np.linalg.norm(u)
    v = np.cross(n, u)
    Q = [(float((q - P[0]) @ u), float((q - P[0]) @ v)) for q in P]

    def area(a, b, c):
        return (Q[b][0] - Q[a][0]) * (Q[c][1] - Q[a][1]) - (Q[c][0] - Q[a][0]) * (Q[b][1] - Q[a][1])
    idx = list(range(len(P)))
    tris = []
    while len(idx) > 3:
        found = None
        for k in range(len(idx)):
            a, b, c = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            if area(a, b, c) <= 0:
                continue
            if any(area(a, b, m) >= 0 and area(b, c, m) >= 0 and area(c, a, m) >= 0 for m in idx if m not in (a, b, c)):
                continue
            found = k
            break
        if found is None:
            return None
        a, b, c = idx[found - 1], idx[found], idx[(found + 1) % len(idx)]
        tris.append((a, b, c))
        idx.pop(found)
    tris.append(tuple(idx))
    return tris


def _check_closed(faces):
    """every directed edge (consecutive loop vertices) used exactly once, and its reverse exactly once"""
    E = collections.Counter()
    for fc in faces:
        for lp in fc:
            for a, b in zip(lp, lp[1:] + lp[:1]):
                E[(a, b)] += 1
    for (a, b), m in E.items():
        if m != 1 or E.get((b, a), 0) != 1:
            return False
    return True


def _cylinder(solid):
    """a right circular cylinder solid (one cylindrical face, two planar caps square to its axis) ->
    (origin at the low cap, axis, ref x, radius, height); None otherwise"""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane, GeomAbs_Cylinder
    from OCP.TopAbs import TopAbs_FACE, TopAbs_VERTEX
    from OCP.TopoDS import TopoDS
    faces = _children(solid, TopAbs_FACE)
    if len(faces) != 3:
        return None
    cyl, caps = None, []
    for fc in faces:
        ad = BRepAdaptor_Surface(_cast('Face', fc))
        t = ad.GetType()
        if t == GeomAbs_Cylinder and cyl is None:
            cyl = ad.Cylinder()
        elif t == GeomAbs_Plane:
            caps.append(ad.Plane())
        else:
            return None
    if cyl is None or len(caps) != 2:
        return None
    a = cyl.Axis()
    o = np.array([a.Location().X(), a.Location().Y(), a.Location().Z()])
    z = np.array([a.Direction().X(), a.Direction().Y(), a.Direction().Z()])
    xd = cyl.XAxis().Direction()
    x = np.array([xd.X(), xd.Y(), xd.Z()])
    R = cyl.Radius()
    for pl in caps:
        n = pl.Axis().Direction()
        if abs(abs(n.X() * z[0] + n.Y() * z[1] + n.Z() * z[2]) - 1.0) > 1e-9:
            return None
    ts = []
    for v in _children(solid, TopAbs_VERTEX):
        p = np.array(_pnt(v))
        ts.append(float(np.dot(p - o, z)))
        if abs(np.linalg.norm((p - o) - np.dot(p - o, z) * z) - R) > 1e-6 * max(1.0, R):
            return None
    if not ts:
        return None
    t0, t1 = min(ts), max(ts)
    # caps at the extreme stations
    hs = sorted(float(np.dot(np.array([pl.Location().X(), pl.Location().Y(), pl.Location().Z()]) - o, z)) for pl in caps)
    if abs(hs[0] - t0) > 1e-6 * max(1.0, abs(t1 - t0)) or abs(hs[1] - t1) > 1e-6 * max(1.0, abs(t1 - t0)):
        return None
    return o + z * t0, z, x, R, t1 - t0


def prim_items(shape):
    """[('brep', faces) | ('cyl', params) | ('surface', faces)] of a shape without provenance"""
    from OCP.TopAbs import TopAbs_SOLID, TopAbs_SHELL, TopAbs_FACE
    out = []
    for so in _children(shape, TopAbs_SOLID):
        shells = _children(so, TopAbs_SHELL)
        c = _cylinder(so) if len(shells) == 1 else None
        if c is not None:
            out.append(('cyl', c))
            continue
        if len(shells) != 1:
            raise Unsupported('solid with %d shells' % len(shells))
        faces = [_face_loops(f) for f in _children(so, TopAbs_FACE)]
        if not _check_closed(faces):
            raise Unsupported('faceted shell not closed / not consistently oriented')
        out.append(('brep', faces))
    for sh in _children(shape, TopAbs_SHELL, TopAbs_SOLID):
        out.append(('surface', [_face_loops(f) for f in _children(sh, TopAbs_FACE)]))
    loose = _children(shape, TopAbs_FACE, TopAbs_SHELL)
    if loose:
        out.append(('surface', [_face_loops(f) for f in loose]))
    if not out:
        raise Unsupported('no geometry')
    return out


def recipe(S):
    """('cut', recipe(base), tools) | ('prim', S)"""
    i = _CUT.FindIndex(S)
    if i:
        base, tools = _CUT_INFO[i]
        return ('cut', recipe(base), tools)
    return ('prim', S)


def unwrap(S, M):
    """placed copies back to their source shape: (source shape, world transform 3x4)"""
    for _ in range(16):
        j = _TRN.FindIndex(S)
        if not j:
            break
        src, M2 = _TRN_INFO[j]
        M = _compose(M, M2)
        S = src
    return S, M


def _compose(A, B):
    """3x4 A o B"""
    Ra, ta, Rb, tb = A[:, :3], A[:, 3], B[:, :3], B[:, 3]
    return np.hstack([Ra @ Rb, (Ra @ tb + ta)[:, None]])


def _loc_matrix(loc):
    t = loc.Transformation()
    return np.array([[t.Value(r, c) for c in (1, 2, 3, 4)] for r in (1, 2, 3)], float)


# ======================================================================================== emit
def _name(lab):
    from OCP.TDataStd import TDataStd_Name
    a = TDataStd_Name()
    return a.Get().ToExtString() if lab.FindAttribute(TDataStd_Name.GetID_s(), a) else ''


LABEL_RX = re.compile(r"^\s*(.*?)\s*#(\d+) / (.*?) \(piece (\d+), inst (\d+)\)")
TURNED_RX = re.compile(r"(WS|TWS|HS|BLT|AB|RB|RD|NS|DBA|THD|STUD)\b|(WS|TWS|HS|RB|RD|AB|DBA)\d")


def _classify(label, piece_kind):
    """IFC class, predefined type, member key, member type, piece id, piece name of one instance label"""
    m = LABEL_RX.match(label)
    if label.startswith('BOLT '):
        return 'IfcMechanicalFastener', '.BOLT.', None, None, None, 'BOLT'
    if m:
        mtype, mem, pname, pid = m.group(1), int(m.group(2)), m.group(3), int(m.group(4))
        k = piece_kind.get(pid, '')
        if '[reference' in label or 'reference part' in pname:
            cls, pt = 'IfcBuildingElementProxy', '.NOTDEFINED.'
        elif pname.startswith('BLT'):
            cls, pt = 'IfcMechanicalFastener', '.BOLT.'
        elif pname.startswith('Conc') or k == 'concrete':
            cls, pt = 'IfcFooting', '.NOTDEFINED.'
        elif TURNED_RX.match(pname) and not pname.startswith(('RB', 'RD')):
            cls, pt = 'IfcMechanicalFastener', '.NOTDEFINED.'
        elif k == 'plate' or pname.startswith(('PL', 'FL', 'GT', 'GR')):
            cls, pt = 'IfcPlate', '.NOTDEFINED.'
        else:
            cls, pt = 'IfcMember', '.NOTDEFINED.'
        return cls, pt, mem, mtype, pid, pname
    m2 = re.match(r"^\s*(.*?)\s*#(\d+) / (.*?) \((member envelope|joist stand-in)\)", label)
    if m2:
        mtype = m2.group(1)
        cls = {'BEAM': 'IfcBeam', 'COLUMN': 'IfcColumn', 'JOIST': 'IfcBeam'}.get(mtype.upper(), 'IfcMember')
        return cls, '.NOTDEFINED.', int(m2.group(2)), mtype, None, m2.group(3)
    return 'IfcBuildingElementProxy', '.NOTDEFINED.', None, None, None, ''


def emit(doc, step_path):
    t0 = time.time()
    from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool
    from OCP.TDF import TDF_Label
    try:
        from OCP.TDF import TDF_LabelSequence
    except ImportError:
        from OCP.collections import Sequence_TDF_Label as TDF_LabelSequence
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    roots = TDF_LabelSequence()
    st.GetFreeShapes(roots)
    I3 = np.hstack([np.eye(3), np.zeros((3, 1))])
    inst = []          # (label, shape, M)
    root_name = ''
    for i in range(1, roots.Length() + 1):
        lab = roots.Value(i)
        if XCAFDoc_ShapeTool.IsAssembly_s(lab):
            root_name = root_name or _name(lab)
            comps = TDF_LabelSequence()
            XCAFDoc_ShapeTool.GetComponents_s(lab, comps, False)
            for j in range(1, comps.Length() + 1):
                c = comps.Value(j)
                ref = TDF_Label()
                XCAFDoc_ShapeTool.GetReferredShape_s(c, ref)
                inst.append((_name(c) or _name(ref), XCAFDoc_ShapeTool.GetShape_s(ref),
                             _loc_matrix(XCAFDoc_ShapeTool.GetLocation_s(c))))
        else:
            inst.append((_name(lab), XCAFDoc_ShapeTool.GetShape_s(lab), I3.copy()))
    # piece kinds for the IFC class (the converter's own piece table)
    piece_kind = {}
    try:
        from piece_table import read_pieces, kind
        pieces = read_pieces(META['job'])
        piece_kind = {k: kind(p) for k, p in pieces.items()}
    except Exception:
        pass
    salt = META['shipped_sha256']
    F = _File()
    origin = F.add("IFCCARTESIANPOINT((0.,0.,0.))")
    ctx_wcs = F.add("IFCAXIS2PLACEMENT3D(%s,$,$)" % origin)
    ctx = F.add("IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,%s,$)" % ctx_wcs)
    body = F.add("IFCGEOMETRICREPRESENTATIONSUBCONTEXT('Body','Model',*,*,*,*,%s,$,.MODEL_VIEW.,$)" % ctx)
    u1 = F.add("IFCSIUNIT(*,.LENGTHUNIT.,.MILLI.,.METRE.)")
    u2 = F.add("IFCSIUNIT(*,.PLANEANGLEUNIT.,$,.RADIAN.)")
    units = F.add("IFCUNITASSIGNMENT((%s,%s))" % (u1, u2))
    g = lambda key: _str(sds2label.guid(salt, key))
    proj = F.add("IFCPROJECT(%s,$,%s,%s,$,$,$,(%s),%s)" % (g('\x00project'), _str(root_name or META.get('model_id')),
                 _str('SDS/2 job emitted as IFC from the converter %s; shipped STEP sha256 %s' % (META.get('converter', ''), salt)),
                 ctx, units))
    ax0 = F.add("IFCAXIS2PLACEMENT3D(%s,$,$)" % origin)
    lp0 = lambda: F.add("IFCLOCALPLACEMENT($,%s)" % ax0)
    site = F.add("IFCSITE(%s,$,'Site',$,$,%s,$,$,.ELEMENT.,$,$,$,$,$)" % (g('\x00site'), lp0()))
    bldg = F.add("IFCBUILDING(%s,$,'Building',$,$,%s,$,$,.ELEMENT.,$,$,$)" % (g('\x00building'), lp0()))
    stor = F.add("IFCBUILDINGSTOREY(%s,$,'Storey',$,$,%s,$,$,.ELEMENT.,$)" % (g('\x00storey'), lp0()))
    F.add("IFCRELAGGREGATES(%s,$,$,$,%s,(%s))" % (g('\x00rel project'), proj, site))
    F.add("IFCRELAGGREGATES(%s,$,$,$,%s,(%s))" % (g('\x00rel site'), site, bldg))
    F.add("IFCRELAGGREGATES(%s,$,$,$,%s,(%s))" % (g('\x00rel building'), bldg, stor))
    dz = F.add("IFCDIRECTION((0.,0.,1.))")
    o2 = F.add("IFCAXIS2PLACEMENT2D(%s,$)" % F.add("IFCCARTESIANPOINT((0.,0.))"))
    ident_op = F.add("IFCCARTESIANTRANSFORMATIONOPERATOR3D($,$,%s,$,$)" % origin)
    parts = _shape_map()
    part_map = {}            # part index -> IfcRepresentationMap
    part_info = {}
    stats = collections.Counter()
    unsupported = []
    tool_cache = {}

    def pt3(p, cache):
        k = (p[0], p[1], p[2])
        r = cache.get(k)
        if r is None:
            r = cache[k] = F.add("IFCCARTESIANPOINT((%s,%s,%s))" % (_real(p[0]), _real(p[1]), _real(p[2])))
        return r

    def pt(p):
        return F.add("IFCCARTESIANPOINT((%s,%s,%s))" % (_real(p[0]), _real(p[1]), _real(p[2])))

    def dirn(v):
        return F.add("IFCDIRECTION((%s,%s,%s))" % (_real(v[0]), _real(v[1]), _real(v[2])))

    def faces_ent(faces, cache):
        out = []
        for fc in faces:
            if len(fc) == 1 and _spike(fc[0]):
                # a loop that turns back on itself at a vertex (a sliver spike: SDS/2 fillet ends, 0.03 mm wide) is
                # simplified away by the IfcOpenShell kernel ('self-intersections ... cycles'), which then leaves the
                # shell open; the same polygon as triangles (same plane, same boundary edges) builds as stated
                tris = _ear_clip(fc[0])
                if tris:
                    stats['faces_split_into_triangles'] += 1
                    for tri in tris:
                        pl = F.add("IFCPOLYLOOP(%s)" % _tup([pt3(fc[0][i], cache) for i in tri]))
                        out.append(F.add("IFCFACE((%s))" % F.add("IFCFACEOUTERBOUND(%s,.T.)" % pl)))
                    continue
            bnds = []
            for k, lp in enumerate(fc):
                pl = F.add("IFCPOLYLOOP(%s)" % _tup([pt3(p, cache) for p in lp]))
                bnds.append(F.add("%s(%s,.T.)" % ('IFCFACEOUTERBOUND' if k == 0 else 'IFCFACEBOUND', pl)))
            out.append(F.add("IFCFACE(%s)" % _tup(bnds)))
        return out

    def tool_ent(t):
        key = json.dumps(t, sort_keys=True)
        if key in tool_cache:
            return tool_cache[key]
        a = np.asarray(t['a'])
        if t['kind'] == 'circle':
            x = np.cross(a, [0.0, 0.0, 1.0] if abs(a[2]) < 0.9 else [1.0, 0.0, 0.0]); x /= np.linalg.norm(x)
            prof = F.add("IFCCIRCLEPROFILEDEF(.AREA.,$,%s,%s)" % (o2, _real(t['r'])))
            pos = F.add("IFCAXIS2PLACEMENT3D(%s,%s,%s)" % (pt(t['p0']), dirn(a), dirn(x)))
        else:
            s, r = t['s'], t['r']
            pts = [(-s, -r), (s, -r), (s + r, 0.0), (s, r), (-s, r), (-s - r, 0.0)]
            pl = F.add("IFCCARTESIANPOINTLIST2D((%s))" % ','.join('(%s,%s)' % (_real(u), _real(v)) for u, v in pts))
            crv = F.add("IFCINDEXEDPOLYCURVE(%s,(IFCLINEINDEX((1,2)),IFCARCINDEX((2,3,4)),IFCLINEINDEX((4,5)),IFCARCINDEX((5,6,1))),.F.)" % pl)
            prof = F.add("IFCARBITRARYCLOSEDPROFILEDEF(.AREA.,'slot',%s)" % crv)
            pos = F.add("IFCAXIS2PLACEMENT3D(%s,%s,%s)" % (pt(t['p0']), dirn(a), dirn(t['d'])))
        e = F.add("IFCEXTRUDEDAREASOLID(%s,%s,%s,%s)" % (prof, pos, dz, _real(t['L'])))
        tool_cache[key] = e
        return e

    def prim_ents(items, cache):
        ents, kinds = [], []
        for kind, data in items:
            if kind == 'brep':
                ents.append(F.add("IFCFACETEDBREP(%s)" % F.add("IFCCLOSEDSHELL(%s)" % _tup(faces_ent(data, cache)))))
            elif kind == 'surface':
                ents.append(F.add("IFCSHELLBASEDSURFACEMODEL((%s))" % F.add("IFCOPENSHELL(%s)" % _tup(faces_ent(data, cache)))))
            else:
                o, z, x, R, h = data
                prof = F.add("IFCCIRCLEPROFILEDEF(.AREA.,$,%s,%s)" % (o2, _real(R)))
                pos = F.add("IFCAXIS2PLACEMENT3D(%s,%s,%s)" % (pt(o), dirn(z), dirn(x)))
                ents.append(F.add("IFCEXTRUDEDAREASOLID(%s,%s,%s,%s)" % (prof, pos, dz, _real(h))))
            kinds.append(kind)
        return ents, kinds

    def part_rep(S):
        rec = recipe(S)
        tools = []
        while rec[0] == 'cut':
            tools = rec[2] + tools
            rec = rec[1]
        items = prim_items(rec[1])
        cache = {}
        ents, kinds = prim_ents(items, cache)
        if tools:
            if any(k == 'surface' for k in kinds):
                raise Unsupported('holes cut into an open surface')
            tents = [tool_ent(t) for t in tools]
            out = []
            for e in ents:
                cur = e
                for te in tents:
                    cur = F.add("IFCBOOLEANRESULT(.DIFFERENCE.,%s,%s)" % (cur, te))
                out.append(cur)
            ents = out
            rtype = 'CSG'
        else:
            ks = set(kinds)
            rtype = 'Brep' if ks == {'brep'} else 'SweptSolid' if ks == {'cyl'} else 'SurfaceModel' if ks == {'surface'} else 'SolidModel'
        rep = F.add("IFCSHAPEREPRESENTATION(%s,'Body',%s,%s)" % (body, _str(rtype), _tup(ents)))
        rmap = F.add("IFCREPRESENTATIONMAP(%s,%s)" % (ax0, rep))
        return rmap, dict(items=collections.Counter(kinds), tools=len(tools))

    seen = collections.Counter()
    members = collections.OrderedDict()
    loose = []
    rows = []
    for label, S, M in inst:
        S, M = unwrap(S, M)
        k = parts.FindIndex(S)
        if not k:
            k = parts.Add(S)
            try:
                part_map[k], part_info[k] = part_rep(S)
            except Unsupported as e:
                part_map[k], part_info[k] = None, dict(error=str(e))
                unsupported.append(dict(label=label, why=str(e)))
        rmap = part_map[k]
        occ = seen[label.strip()]
        seen[label.strip()] += 1
        gid = sds2label.guid(salt, sds2label.key(label, occ))
        if rmap is None:
            stats['instances_not_emitted'] += 1
            rows.append(dict(label=label, guid=gid, part=k, emitted=False))
            continue
        R = M[:, :3]
        sc = np.cbrt(np.linalg.det(R))
        Rn = R / sc if sc > 0 else R
        if sc <= 0 or abs(sc - 1.0) > 1e-9 or np.max(np.abs(Rn.T @ Rn - np.eye(3))) > 1e-9:
            stats['placement_not_rigid'] += 1
            unsupported.append(dict(label=label, why='placement not a rotation (scale %.12g)' % sc))
            rows.append(dict(label=label, guid=gid, part=k, emitted=False))
            continue
        z, x, t = Rn[:, 2], Rn[:, 0], M[:, 3]
        if np.allclose(Rn, np.eye(3), atol=0, rtol=0) and not np.any(t):
            plc = F.add("IFCLOCALPLACEMENT($,%s)" % ax0)
        else:
            plc = F.add("IFCLOCALPLACEMENT($,%s)" % F.add("IFCAXIS2PLACEMENT3D(%s,%s,%s)" % (pt(t), dirn(z), dirn(x))))
        mi = F.add("IFCMAPPEDITEM(%s,%s)" % (rmap, ident_op))
        sr = F.add("IFCSHAPEREPRESENTATION(%s,'Body','MappedRepresentation',(%s))" % (body, mi))
        shape = F.add("IFCPRODUCTDEFINITIONSHAPE($,$,(%s))" % sr)
        cls, ptype, mem, mtype, pid, pname = _classify(label, piece_kind)
        tag = _str('P%d' % pid) if pid is not None else '$'
        if cls == 'IfcMechanicalFastener':
            e = F.add("%s(%s,$,%s,$,%s,%s,%s,%s,$,$,%s)" % (cls.upper(), _str(gid), _str(label), _str(pname), plc, shape, tag, ptype))
        else:
            e = F.add("%s(%s,$,%s,$,%s,%s,%s,%s,%s)" % (cls.upper(), _str(gid), _str(label), _str(pname), plc, shape, tag, ptype))
        stats[cls] += 1
        if mem is not None:
            members.setdefault((mem, mtype), []).append(e)
        else:
            loose.append(e)
        rows.append(dict(label=label, guid=gid, part=k, emitted=True, cls=cls))
    contained = list(loose)
    for (mem, mtype), els in members.items():
        a = F.add("IFCELEMENTASSEMBLY(%s,$,%s,$,%s,%s,$,%s,.FACTORY.,.NOTDEFINED.)" % (
            g('\x00member %d' % mem), _str('%s #%d' % (mtype, mem)), _str(mtype), lp0(), _str('M%d' % mem)))
        F.add("IFCRELAGGREGATES(%s,$,$,$,%s,%s)" % (g('\x00rel member %d' % mem), a, _tup(els)))
        contained.append(a)
    if contained:
        F.add("IFCRELCONTAINEDINSPATIALSTRUCTURE(%s,$,$,$,%s,%s)" % (g('\x00rel storey'), _tup(contained), stor))
    base = os.path.splitext(step_path)[0]
    hdr = ("ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('ViewDefinition [DesignTransferView]'),'2;1');\n"
           "FILE_NAME(%s,'2026-10-07T00:00:00',('Deccan'),('Deccan'),%s,%s,'');\nFILE_SCHEMA(('IFC4'));\nENDSEC;\nDATA;\n" % (
               _str(META.get('model_id', '') + '.ifc'), _str('%s %s' % (EMITTER, EMITTER_VERSION)),
               _str('%s %s / sds2-step-pipeline %s' % (EMITTER, EMITTER_VERSION, META.get('converter', '')))))
    tmp = base + '.ifc.tmp'
    with open(tmp, 'w', encoding='ascii') as fh:
        fh.write(hdr)
        for ln in F.lines:
            fh.write(ln + '\n')
        fh.write('ENDSEC;\nEND-ISO-10303-21;\n')
    os.replace(tmp, base + '.ifc')
    dup = {k: v for k, v in seen.items() if v > 1}
    info = dict(emitter=EMITTER, emitter_version=EMITTER_VERSION, model_id=META.get('model_id'), converter=META.get('converter'),
                shipped_sha256=salt, root=root_name, instances=len(inst), instances_emitted=sum(1 for r in rows if r['emitted']),
                unique_parts=parts.Extent(), parts_by_items=dict(collections.Counter(json.dumps(v.get('items', {}), sort_keys=True) for v in part_info.values())),
                parts_with_holes=sum(1 for v in part_info.values() if v.get('tools')), hole_tools=sum(v.get('tools', 0) for v in part_info.values()),
                classes=dict(stats), unsupported=unsupported[:200], unsupported_count=len(unsupported),
                duplicate_labels=len(dup), duplicate_label_examples=list(dup)[:10], cut_results_recorded=_CUT.Extent(),
                placed_copies_recorded=_TRN.Extent(), hook_errors=META.get('hook_errors', [])[:20], seconds=round(time.time() - t0, 1),
                ifc_bytes=os.path.getsize(base + '.ifc'),
                ifc_sha256=hashlib.sha256(open(base + '.ifc', 'rb').read()).hexdigest())
    json.dump(info, open(base + '_ifc_emit.json', 'w'), indent=1)
    with open(base + '_ifc_products.jsonl', 'w') as fh:
        for r in rows:
            fh.write(json.dumps(r) + '\n')
    print('IFC emitted: %d instances, %d unique parts, %d unsupported -> %s' % (len(inst), parts.Extent(), len(unsupported), base + '.ifc'))
