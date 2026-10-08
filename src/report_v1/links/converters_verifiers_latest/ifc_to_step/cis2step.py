#!/usr/bin/env python3
"""cis2step - CIS/2 LPM/6 (STRUCTURAL_FRAME_SCHEMA) manufacturing model -> STEP AP214 (exact B-rep), one PRODUCT per
LOCATED_PART_MARKED.

usage: cis2step.py IN.stp|ifc OUT.step [--parts OUT.parts.json] [--census OUT.census.json --src-parts OUT.src_parts.jsonl.gz]

Built ONLY from what the file stores (no invented geometry):
  * PART_PRISMATIC_SIMPLE: the SECTION_PROFILE_* (stored dimensions) swept along the part's local x by the stored length,
    section in the local y-z plane placed by its stored cardinal point, at the LOCATED_PART's COORD_SYSTEM chain
    (COORD_SYSTEM_CHILD -> parent ... -> global).
  * PART_PRISMATIC_SIMPLE_CURVED: the section swept along the stored curve (polyline) when the sweep gives a valid solid.
  * PART_SHEET_BOUNDED_COMPLEX: the stored boundary polygon extruded by the stored thickness, centred on the boundary plane.
  * holes (FEATURE_VOLUME_HOLE_CIRCULAR, with or without FEATURE_VOLUME_WITH_LAYOUT): cylinders of the stored radius at the
    stored positions, along the stored hole-depth direction, cut through the element.
Everything else is TAGGED, never guessed (the part keeps its uncut body and the tag says what is missing):
  feature_not_applied:<FEATURE type>  copes / notches / skewed ends / chamfers / slotted holes / complex features
  root_radius_not_stored / corner_radius_not_stored  rolled section built sharp-cornered: the file leaves the radius out
  camber_not_applied  PART_PRISMATIC_SIMPLE_CAMBERED (a shop instruction; the modelled member is straight)
  bolts: JOINT_SYSTEM_MECHANICAL bolt positions are stored, head / nut geometry is not -> counted, not built
Exit codes: 0 ok, 2 not CIS/2, 3 parse error, 4 nothing built."""
import sys, os, re, json, math, gzip, time, argparse, collections
import numpy as np

VERSION = 'cis2step 0.2.1'
IN_MM = 25.4                     # international inch, exact by definition (CONTEXT_DEPENDENT_UNIT 'inch')
UNIT_MM = {'inch': 25.4, 'in': 25.4, 'foot': 304.8, 'ft': 304.8, 'millimetre': 1.0, 'millimeter': 1.0, 'mm': 1.0, 'metre': 1000.0, 'meter': 1000.0}

# ------------------------------------------------------------------ ISO 10303-21 reader (simple + complex instances)
class Ref(int):
    __slots__ = ()
class Enum(str):
    __slots__ = ()
class Typed:
    __slots__ = ('name', 'args')
    def __init__(self, n, a): self.name, self.args = n, a
class Inst:
    __slots__ = ('id', 'parts')
    def __init__(self, i, parts): self.id, self.parts = i, parts
    def is_a(self, n): return n in self.parts
    @property
    def types(self): return tuple(self.parts)
    def __getitem__(self, n): return self.parts[n]

TOK = re.compile(r"""\s*(?:(?P<str>'(?:[^']|'')*')|(?P<ref>\#\d+)|(?P<enum>\.[A-Z0-9_]+\.)|(?P<num>[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)|(?P<kw>[A-Z_][A-Z0-9_]*)|(?P<p>[(),$*])|(?P<bin>"[0-9A-F]*"))""")
RX_OPEN = re.compile(r'\s*\(')

def _args(s, pos):
    pos += 1; out = []
    while True:
        m = TOK.match(s, pos)
        if not m: raise ValueError(f'bad token at {s[pos:pos + 60]!r}')
        pos = m.end(); g = m.lastgroup; v = m.group(g)
        if g == 'p':
            if v == ')': return out, pos
            if v == ',': continue
            if v == '(':
                sub, pos = _args(s, m.end() - 1); out.append(sub); continue
            out.append(None if v == '$' else '*'); continue
        if g == 'str': out.append(v[1:-1].replace("''", "'"))
        elif g == 'ref': out.append(Ref(int(v[1:])))
        elif g == 'enum': out.append(Enum(v[1:-1]))
        elif g == 'num': out.append(float(v) if ('.' in v or 'e' in v or 'E' in v) else int(v))
        elif g == 'kw':
            m2 = RX_OPEN.match(s, pos); sub, pos = _args(s, m2.end() - 1); out.append(Typed(v, sub))
        else: out.append(v)

def _strip_comments(s):
    out = []; i = 0; n = len(s)
    while i < n:
        j = i
        while j < n and s[j] not in "'/": j += 1
        out.append(s[i:j]); i = j
        if i >= n: break
        if s[i] == "'":
            j = i + 1
            while True:
                j = s.index("'", j)
                if j + 1 < n and s[j + 1] == "'": j += 2; continue
                break
            out.append(s[i:j + 1]); i = j + 1
        elif s.startswith('/*', i):
            i = s.index('*/', i + 2) + 2
        else:
            out.append('/'); i += 1
    return ''.join(out)

def read_spf(path):
    s = _strip_comments(open(path, encoding='latin1').read())
    d0 = s.index('DATA;')
    m = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", s[:d0])
    schema = m.group(1) if m else None
    hdr = s[:d0]
    body = s[d0 + 5:]; body = body[:body.rindex('ENDSEC;')]
    ents = {}; pos = 0
    rx = re.compile(r'\s*#(\d+)\s*=\s*'); rk = re.compile(r'\s*([A-Z_][A-Z0-9_]*)\s*'); rend = re.compile(r'\s*\)\s*;'); rsemi = re.compile(r'\s*;')
    while True:
        m = rx.match(body, pos)
        if not m: break
        iid = int(m.group(1)); pos = m.end()
        if body[pos] == '(':
            pos += 1; parts = {}
            while True:
                m2 = rk.match(body, pos)
                if not m2:
                    pos = rend.match(body, pos).end(); break
                a, pos = _args(body, m2.end()); parts[m2.group(1)] = a
        else:
            m2 = rk.match(body, pos); a, pos = _args(body, m2.end()); parts = {m2.group(1): a}
            pos = rsemi.match(body, pos).end()
        ents[iid] = Inst(iid, parts)
    return schema, hdr, ents

# ------------------------------------------------------------------ model access
class Model:
    def __init__(self, E):
        self.E = E; self._cs = {}; self.unit_mm = None; self.units = collections.Counter()
    def first(self, i):
        e = self.E[i]; return e.parts[next(iter(e.parts))]
    def length(self, i):
        """*_MEASURE_WITH_UNIT -> value in mm (unit chain checked: CONTEXT_DEPENDENT_UNIT name / SI_UNIT)"""
        if i is None: return None
        a = self.first(i); v = a[0].args[0] if isinstance(a[0], Typed) else a[0]
        return float(v) * self.unit_of(a[1])
    def angle(self, i):
        if i is None: return None
        a = self.first(i); v = a[0].args[0] if isinstance(a[0], Typed) else a[0]
        u = self.E[a[1]]
        if u.is_a('SI_UNIT') and str(u['SI_UNIT'][1]) == 'RADIAN': return float(v)
        raise ValueError('angle unit not radian')
    def unit_of(self, uid):
        u = self.E[uid]
        if u.is_a('CONTEXT_DEPENDENT_UNIT'):
            nm = str(u['CONTEXT_DEPENDENT_UNIT'][0]).strip().lower()
            if nm not in UNIT_MM: raise ValueError(f'unknown length unit {nm!r}')
            self.units[nm] += 1; return UNIT_MM[nm]
        if u.is_a('SI_UNIT'):
            pre = u['SI_UNIT'][0]; nm = str(u['SI_UNIT'][1])
            if nm != 'METRE': raise ValueError(f'unit {nm}')
            f = {None: 1000.0, 'MILLI': 1.0, 'CENTI': 10.0}.get(pre)
            self.units['SI ' + str(pre) + nm] += 1; return f
        raise ValueError(f'unit entity {u.types}')
    def P(self, i):
        return np.array(self.first(i)[1], float)
    def D(self, i):
        v = np.array(self.first(i)[1], float); return v / np.linalg.norm(v)
    def a2p(self, i):
        a = self.E[i]['AXIS2_PLACEMENT_3D']
        o = self.P(a[1]) * self.unit_mm
        z = self.D(a[2]) if a[2] else np.array([0, 0, 1.0]); x = self.D(a[3]) if a[3] else np.array([1.0, 0, 0])
        x = x - z * (x @ z); x /= np.linalg.norm(x); y = np.cross(z, x)
        M = np.eye(4); M[:3, 0] = x; M[:3, 1] = y; M[:3, 2] = z; M[:3, 3] = o
        return M
    def cs(self, i, depth=0):
        """world matrix (mm) of a COORD_SYSTEM (child chains resolved)"""
        if i in self._cs: return self._cs[i]
        if depth > 64: raise ValueError('coord system chain too deep')
        e = self.E[i]
        M = self.a2p(e['COORD_SYSTEM_CARTESIAN_3D'][-1])
        if e.is_a('COORD_SYSTEM_CHILD'):
            M = self.cs(e['COORD_SYSTEM_CHILD'][0], depth + 1) @ M
        self._cs[i] = M; return M
    def polyline_pts(self, i):
        """POLYLINE / BOUNDED_SURFACE_CURVE / COMPOSITE_CURVE(_SEGMENT) / BOUNDARY_CURVE -> [N,3] points in file units"""
        e = self.E[i]
        if e.is_a('POLYLINE'):
            return [self.P(q) for q in e['POLYLINE'][1]]
        if e.is_a('BOUNDED_SURFACE_CURVE'):
            return self.polyline_pts(e['BOUNDED_SURFACE_CURVE'][1])
        if e.is_a('COMPOSITE_CURVE_SEGMENT'):
            pts = self.polyline_pts(e['COMPOSITE_CURVE_SEGMENT'][2])
            return pts if e['COMPOSITE_CURVE_SEGMENT'][1] in (True, 'T', Enum('T')) or str(e['COMPOSITE_CURVE_SEGMENT'][1]) == 'T' else pts[::-1]
        for t in ('BOUNDARY_CURVE', 'COMPOSITE_CURVE'):
            if e.is_a(t):
                out = []
                for sgi in e[t][1]:
                    p = self.polyline_pts(sgi)
                    if out and np.allclose(out[-1], p[0]): p = p[1:]
                    out += p
                return out
        raise ValueError(f'curve type {e.types} not supported')

# ------------------------------------------------------------------ OCC geometry
from OCC.Core.gp import gp_Pnt, gp_Dir, gp_Ax2, gp_Vec, gp_Trsf, gp_Circ, gp_Ax1
from OCC.Core.BRepBuilderAPI import (BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace, BRepBuilderAPI_Transform,
                                     BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire)
from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakePrism, BRepPrimAPI_MakeCylinder
from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCC.Core.BRepCheck import BRepCheck_Analyzer
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib
from OCC.Core.TopoDS import TopoDS_Compound
from OCC.Core.BRep import BRep_Builder
from OCC.Core.GC import GC_MakeArcOfCircle
from OCC.Core.TopTools import TopTools_ListOfShape
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_SOLID

def _wire_yz(loop):
    """closed polygon of (y, z) section points in the local x = 0 plane"""
    mp = BRepBuilderAPI_MakePolygon()
    for y, z in loop: mp.Add(gp_Pnt(0.0, float(y), float(z)))
    mp.Close(); return mp.Wire()

def face_yz(outer, holes=()):
    f = BRepBuilderAPI_MakeFace(_wire_yz(outer), True)
    for h in holes:
        w = _wire_yz(h[::-1]); f.Add(w)
    return f.Face()

def circle_face_yz(r, cy, cz, r_in=None):
    ax = gp_Ax2(gp_Pnt(0, cy, cz), gp_Dir(1, 0, 0))
    w = BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(gp_Circ(ax, r)).Edge()).Wire()
    f = BRepBuilderAPI_MakeFace(w, True)
    if r_in:
        wi = BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(gp_Circ(ax, r_in)).Edge()).Wire(); wi.Reverse(); f.Add(wi)
    return f.Face()

def mixed_face_yz(segs):
    """closed outline of ('L', p0, p1) lines and ('A', p0, pmid, p1) arcs in (y, z)"""
    mw = BRepBuilderAPI_MakeWire()
    P3 = lambda p: gp_Pnt(0.0, float(p[0]), float(p[1]))
    for s in segs:
        if s[0] == 'L': mw.Add(BRepBuilderAPI_MakeEdge(P3(s[1]), P3(s[2])).Edge())
        else: mw.Add(BRepBuilderAPI_MakeEdge(GC_MakeArcOfCircle(P3(s[1]), P3(s[2]), P3(s[3])).Value()).Edge())
    return BRepBuilderAPI_MakeFace(mw.Wire(), True).Face()

def prism_x(face, length):
    return BRepPrimAPI_MakePrism(face, gp_Vec(float(length), 0, 0)).Shape()

def place(shape, M):
    t = gp_Trsf()
    t.SetValues(*[float(M[r, c]) for r in range(3) for c in range(4)])
    return BRepBuilderAPI_Transform(shape, t, True).Shape()

def volume(sh):
    g = GProp_GProps(); brepgprop.VolumeProperties(sh, g); return g.Mass()

def bbox(sh):
    b = Bnd_Box(); brepbndlib.Add(sh, b, False)
    return list(b.Get()) if not b.IsVoid() else None

# ------------------------------------------------------------------ sections (y = width, z = depth; built about their bbox)
CARD_ROW = {1: 'b', 2: 'b', 3: 'b', 4: 'm', 5: 'm', 6: 'm', 7: 't', 8: 't', 9: 't'}
CARD_COL = {1: 'l', 4: 'l', 7: 'l', 2: 'c', 5: 'c', 8: 'c', 3: 'r', 6: 'r', 9: 'r'}
LEFT_SIGN = 1.0    # 'left' cardinal column = +y: verified on angles (cardinal 1) against SDS/2's own IFC export of the same job (README)

def card_offset(card, ylo, yhi, zlo, zhi):
    if card not in CARD_ROW: return None
    r, c = CARD_ROW[card], CARD_COL[card]
    z = {'b': zlo, 'm': (zlo + zhi) / 2, 't': zhi}[r]
    yl, yr = (ylo, yhi) if LEFT_SIGN < 0 else (yhi, ylo)
    y = {'l': yl, 'c': (ylo + yhi) / 2, 'r': yr}[c]
    return y, z

class Unsupported(Exception):
    pass

def section(m, sid):
    """-> (face in local x=0 plane with the cardinal point at the origin, tags, info)"""
    e = m.E[sid]; t = [x for x in e.types if x.startswith('SECTION_PROFILE_')][-1]; a = e[t]
    name, card, mirrored = a[1], a[4], str(a[5]) == 'T'
    dims = [m.length(x) if isinstance(x, Ref) and 'MEASURE_WITH_UNIT' in m.E[x].types[0] else None for x in a[6:]]
    tags = []; mir = -1.0 if mirrored else 1.0
    if t == 'SECTION_PROFILE_I_TYPE':
        d, b, tw, tf = dims[:4]
        if any(x is not None for x in dims[5:]): raise Unsupported('i_type_radius_or_slope_stored')     # not in these files
        tags.append('root_radius_not_stored')
        poly = [(-b / 2, -d / 2), (b / 2, -d / 2), (b / 2, -d / 2 + tf), (tw / 2, -d / 2 + tf), (tw / 2, d / 2 - tf), (b / 2, d / 2 - tf),
                (b / 2, d / 2), (-b / 2, d / 2), (-b / 2, d / 2 - tf), (-tw / 2, d / 2 - tf), (-tw / 2, -d / 2 + tf), (-b / 2, -d / 2 + tf)]
        ext = (-b / 2, b / 2, -d / 2, d / 2)
        build = lambda off: face_yz([(y - off[0], z - off[1]) for y, z in poly])
    elif t == 'SECTION_PROFILE_CHANNEL':
        d, b, tw, tf = dims[:4]
        if any(x is not None for x in dims[4:]): raise Unsupported('channel_radius_or_slope_stored')
        tags.append('root_radius_not_stored')
        # web on the -y side (mirrored: +y), flanges toward the other side
        tags.append('section_orientation_unverified')       # cardinal 4 left/right + mirror flag not checkable (README)
        poly = [(0, 0), (b, 0), (b, tf), (tw, tf), (tw, d - tf), (b, d - tf), (b, d), (0, d)]
        poly = [(mir * y, z) for y, z in poly]
        ys = [p[0] for p in poly]; ext = (min(ys), max(ys), 0, d)
        build = lambda off: face_yz([(y - off[0], z - off[1]) for y, z in (poly if not mirrored else poly[::-1])])
    elif t == 'SECTION_PROFILE_ANGLE':
        d, b, tk, rr = dims[:4]
        if any(x is not None for x in dims[4:]): raise Unsupported('angle_edge_radius_or_slope_stored')
        # vertical leg (depth d) at y = 0, horizontal leg (width b) toward -y unless mirrored (verified: README)
        mir = 1.0 if mirrored else -1.0; mirrored = mir < 0
        if rr:
            c = (tk + rr, tk + rr); s45 = rr / math.sqrt(2)
            segs = [('L', (0, 0), (b, 0)), ('L', (b, 0), (b, tk)), ('L', (b, tk), (tk + rr, tk)),
                    ('A', (tk + rr, tk), (c[0] - s45, c[1] - s45), (tk, tk + rr)), ('L', (tk, tk + rr), (tk, d)), ('L', (tk, d), (0, d)), ('L', (0, d), (0, 0))]
        else:
            segs = None; tags.append('root_radius_not_stored')
        poly = [(0, 0), (b, 0), (b, tk), (tk, tk), (tk, d), (0, d)]
        ys = [mir * p[0] for p in poly]; ext = (min(ys), max(ys), 0, d)
        def build(off, segs=segs, poly=poly):
            if segs:
                ss = []
                for s in (segs if not mirrored else [(k[0],) + tuple(k[1:][::-1]) for k in segs[::-1]]):
                    ss.append((s[0],) + tuple((mir * p[0] - off[0], p[1] - off[1]) for p in s[1:]))
                return mixed_face_yz(ss)
            pp = [(mir * y - off[0], z - off[1]) for y, z in poly]
            return face_yz(pp if not mirrored else pp[::-1])
    elif t == 'SECTION_PROFILE_CIRCLE':
        r = dims[0]; ext = (-r, r, -r, r)
        build = lambda off: circle_face_yz(r, -off[0], -off[1])
    elif t == 'SECTION_PROFILE_CIRCLE_HOLLOW':
        r, wt = dims[:2]; ext = (-r, r, -r, r)
        build = lambda off: circle_face_yz(r, -off[0], -off[1], r - wt)
    elif t == 'SECTION_PROFILE_RECTANGLE_HOLLOW':
        d, b, ri, wt, ro = dims[:5]
        if ri or ro: raise Unsupported('rhs_corner_radius_stored')
        tags.append('corner_radius_not_stored')
        ext = (-b / 2, b / 2, -d / 2, d / 2)
        build = lambda off: face_yz([(y - off[0], z - off[1]) for y, z in [(-b / 2, -d / 2), (b / 2, -d / 2), (b / 2, d / 2), (-b / 2, d / 2)]],
                                    [[(y - off[0], z - off[1]) for y, z in [(-b / 2 + wt, -d / 2 + wt), (b / 2 - wt, -d / 2 + wt), (b / 2 - wt, d / 2 - wt), (-b / 2 + wt, d / 2 - wt)]]])
    elif t == 'SECTION_PROFILE_CENTRELINE':
        path = m.polyline_pts(a[6]); tk = dims[1]
        if tk is None: raise Unsupported('centreline_thickness_missing')
        yz = [(p[1] * m.unit_mm, p[2] * m.unit_mm) for p in path]
        if any(abs(p[0]) > 1e-9 for p in path): raise Unsupported('centreline_not_in_section_plane')
        poly = thicken(yz, tk)
        ext = None
        build = lambda off: face_yz([(y - off[0], z - off[1]) for y, z in poly])
        if card != 5: raise Unsupported(f'centreline_cardinal_{card}')
        return build((0.0, 0.0)), tags, {'type': t, 'name': name, 'card': card}
    else:
        raise Unsupported(f'section_{t}')
    off = card_offset(card, *ext)
    if off is None: raise Unsupported(f'cardinal_point_{card}')
    return build(off), tags, {'type': t, 'name': name, 'card': card, 'mirrored': mirrored}

def thicken(pts, t):
    """open centreline polyline -> closed outline offset +-t/2 (mitred joins)"""
    P = np.array(pts, float); n = len(P)
    def nrm(a, b):
        d = b - a; d /= np.linalg.norm(d); return np.array([-d[1], d[0]])
    left = []; right = []
    for i in range(n):
        if i == 0: nv = nrm(P[0], P[1]); k = 1.0
        elif i == n - 1: nv = nrm(P[-2], P[-1]); k = 1.0
        else:
            n1, n2 = nrm(P[i - 1], P[i]), nrm(P[i], P[i + 1]); nv = n1 + n2; nv /= np.linalg.norm(nv); k = 1.0 / max(1e-9, nv @ n1)
        left.append(P[i] + nv * t / 2 * k); right.append(P[i] - nv * t / 2 * k)
    return [tuple(p) for p in left + right[::-1]]

# ------------------------------------------------------------------ parts
def build_part(m, lpm):
    """LOCATED_PART_MARKED -> (world shape | None, record)"""
    a = lpm['LOCATED_PART_MARKED']; part = m.E[a[4]]
    rec = {'lpm': lpm.id, 'mark': a[1], 'desc': a[2], 'assembly': None, 'cls': None, 'tags': [], 'status': None}
    try:
        asm = m.E[a[5]] if isinstance(a[5], Ref) else None
        rec['assembly'] = asm['LOCATED_ASSEMBLY_MARKED'][1] if asm is not None and asm.is_a('LOCATED_ASSEMBLY_MARKED') else None
    except Exception:
        pass
    W = m.cs(a[3])
    if part.is_a('PART_PRISMATIC_SIMPLE'):
        rec['cls'] = 'PART_PRISMATIC_SIMPLE'
        pa = part['PART_PRISMATIC_SIMPLE']; length = m.length(pa[1])
        face, tags, info = section(m, pa[0]); rec['tags'] += tags; rec['section'] = info.get('name'); rec['section_type'] = info['type'][16:]
        if part.is_a('PART_PRISMATIC_SIMPLE_CURVED'):
            rec['cls'] = 'PART_PRISMATIC_SIMPLE_CURVED'
            raise Unsupported('curved_part_sweep')
        body = prism_x(face, length)
        if part.is_a('PART_PRISMATIC_SIMPLE_CAMBERED'):
            rec['cls'] = 'PART_PRISMATIC_SIMPLE_CAMBERED'; rec['tags'].append('camber_not_applied')
        rec['length_mm'] = round(length, 3)
    elif part.is_a('PART_SHEET_BOUNDED_COMPLEX') or part.is_a('PART_SHEET_BOUNDED_SIMPLE'):
        rec['cls'] = 'PART_SHEET_BOUNDED_COMPLEX' if part.is_a('PART_SHEET_BOUNDED_COMPLEX') else 'PART_SHEET_BOUNDED_SIMPLE'
        if not part.is_a('PART_SHEET_BOUNDED_COMPLEX'): raise Unsupported('sheet_bounded_simple')
        t = m.length(part['PART_SHEET'][0]); cbs = m.E[part['PART_SHEET_BOUNDED_COMPLEX'][0]]
        if not cbs.is_a('CURVE_BOUNDED_SURFACE'): raise Unsupported('sheet_boundary_type')
        bnds = cbs['CURVE_BOUNDED_SURFACE'][2]
        if len(bnds) != 1: raise Unsupported('sheet_with_inner_boundaries')
        pts = np.array(m.polyline_pts(bnds[0])) * m.unit_mm
        if len(pts) > 3 and np.allclose(pts[0], pts[-1]): pts = pts[:-1]
        c0 = pts.mean(0); u_, s_, vt = np.linalg.svd(pts - c0); nrm = vt[2]
        if s_[2] > 1e-6 * max(1.0, s_[0]): raise Unsupported('sheet_boundary_not_planar')
        # frame: plane basis (e1, e2), normal n; polygon in (e1, e2)
        e1 = vt[0]; e2 = np.cross(nrm, e1)
        loc = [((p - c0) @ e1, (p - c0) @ e2) for p in pts]
        F = np.eye(4); F[:3, 0] = nrm; F[:3, 1] = e1; F[:3, 2] = e2; F[:3, 3] = c0 - nrm * t / 2     # thickness centred on the boundary plane
        body = place(prism_x(face_yz(loc), t), F)
        rec['thickness_mm'] = round(t, 4)
    else:
        rec['cls'] = [x for x in part.types if x.startswith('PART_')][-1] if any(x.startswith('PART_') for x in part.types) else part.types[0]
        raise Unsupported(f'part_type_{rec["cls"]}')
    return W, body, rec

def hole_tools(m, feat_cs_M, F, thick_hint):
    """FEATURE_VOLUME_HOLE_CIRCULAR -> list of cylinders (part-local mm); thick_hint: element thickness span"""
    fc = F['FEATURE_VOLUME_CURVED'][0]; dp = m.polyline_pts(fc)
    p1, p2 = dp[0] * m.unit_mm, dp[-1] * m.unit_mm
    r = m.length(F['FEATURE_VOLUME_HOLE_CIRCULAR'][0])
    axis_l = feat_cs_M[:3, :3] @ (p2 - p1); dlen = float(np.linalg.norm(axis_l))
    if dlen < 1e-9: raise Unsupported('hole_without_depth_direction')
    u = axis_l / dlen
    lay = F['FEATURE_VOLUME_WITH_LAYOUT'][0] if F.is_a('FEATURE_VOLUME_WITH_LAYOUT') else [None]
    out = []
    # plate: a hole goes through the plate -> cut along the whole axis line; rolled section: through the element whose
    # thickness is the stored hole depth (origin on / near its face) -> +-2 x depth. Removed volume is checked by the caller.
    half = (10 * thick_hint + 50.0) if thick_hint else (2 * dlen + 0.01)
    depth = thick_hint if thick_hint else dlen
    for q in lay:
        o = feat_cs_M @ np.r_[(m.P(q) * m.unit_mm) if q is not None else np.zeros(3), 1.0]
        o = o[:3] + feat_cs_M[:3, :3] @ p1
        base = o - u * half
        cyl = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*map(float, base)), gp_Dir(*map(float, u))), float(r), float(2 * half)).Shape()
        out.append(cyl)
    return out, math.pi * r * r * depth * len(out)

def solids_of(sh):
    ex = TopExp_Explorer(sh, TopAbs_SOLID); n = 0
    while ex.More(): n += 1; ex.Next()
    return n

# ------------------------------------------------------------------ STEP writer (AP214, mm, one PRODUCT per part)
def write_step(path, items):
    """items: [(shape, pid, name, desc)] -> STEP; PRODUCT id/name/description set per transferred root"""
    from OCC.Core.STEPControl import STEPControl_Writer, STEPControl_AsIs
    from OCC.Core.Interface import Interface_Static
    from OCC.Core.IFSelect import IFSelect_RetDone
    from OCC.Core.TCollection import TCollection_HAsciiString
    Interface_Static.SetCVal('write.step.schema', 'AP214IS'); Interface_Static.SetCVal('write.step.unit', 'MM')
    Interface_Static.SetCVal('write.step.product.name', 'part')
    w = STEPControl_Writer()
    names = []
    for sh, pid, nm, ds in items:
        st = w.Transfer(sh, STEPControl_AsIs)
        names.append((pid, nm, ds))
    model = w.Model(); k = 0
    from OCC.Core.StepBasic import StepBasic_Product
    for i in range(1, model.NbEntities() + 1):
        ent = model.Value(i)
        if ent.DynamicType().Name() == 'StepBasic_Product':
            p = StepBasic_Product.DownCast(ent)
            if k < len(names):
                pid, nm, ds = names[k]
                p.SetId(TCollection_HAsciiString(pid)); p.SetName(TCollection_HAsciiString(nm or ''))
                p.SetDescription(TCollection_HAsciiString(ds or ''))
            k += 1
    if k != len(names): raise RuntimeError(f'product count {k} != parts {len(names)}')
    if w.Write(path) != IFSelect_RetDone: raise RuntimeError('STEP write failed')
    return k

# ------------------------------------------------------------------ main
OTHER_FEATURES_TAG = 'feature_not_applied'

def convert(src, out, parts_path=None, census_path=None, src_parts_path=None, limit=None):
    T0 = time.time()
    schema, hdr, E = read_spf(src)
    if not schema or not schema.upper().startswith('STRUCTURAL_FRAME'):
        return 2, {'status': 'not_cis2', 'schema': schema}
    m = Model(E)
    lu = [e for e in E.values() if e.is_a('LENGTH_UNIT')]
    if len(lu) != 1: raise ValueError(f'{len(lu)} LENGTH_UNIT entities')
    m.unit_mm = m.unit_of(lu[0].id)
    app = re.search(r"originating_system \*/\s*'([^']*)'", open(src, encoding='latin1').read(8000)) or re.search(r"FILE_NAME\s*\((?:[^;]*?),\s*'([^']*)'\s*,\s*'[^']*'\s*\)\s*;", hdr)
    st = {'version': VERSION, 'schema': schema, 'unit': str(lu[0].parts.get('CONTEXT_DEPENDENT_UNIT', ['SI'])[0]), 'unit_mm': m.unit_mm,
          'originating_system': app.group(1) if app else None}
    lpms = [e for e in E.values() if e.is_a('LOCATED_PART_MARKED')]
    lps_all = [e for e in E.values() if any(t.startswith('LOCATED_PART') for t in e.types)]
    st['located_part_marked'] = len(lpms); st['located_part_total'] = len(lps_all)
    feats = collections.defaultdict(list)
    for e in E.values():
        if e.is_a('LOCATED_FEATURE_FOR_LOCATED_PART'):
            a = e['LOCATED_FEATURE_FOR_LOCATED_PART']; feats[a[5]].append((a[3], a[4], a[1]))
    fstored = collections.Counter(); fapplied = collections.Counter(); fnot = collections.Counter()
    items = []; recs = []; tags_total = collections.Counter(); fail = collections.Counter(); seen_dups = {}; n_dup = 0
    for n_, lpm in enumerate(sorted(lpms, key=lambda e: e.id)):
        if limit and n_ >= limit: break
        rec = None
        try:
            W, body, rec = build_part(m, lpm)
            thick = rec.get('thickness_mm') or 0.0
            tools = []; exp_removed = 0.0; n_holes = 0
            for fcs, fid, flabel in feats.get(lpm.id, []):
                F = E[fid]; ft = [x for x in F.types if x.startswith('FEATURE_VOLUME_')]
                ftype = ('FEATURE_VOLUME_HOLE_CIRCULAR' if F.is_a('FEATURE_VOLUME_HOLE_CIRCULAR') else
                         'FEATURE_VOLUME_HOLE_SLOTTED' if F.is_a('FEATURE_VOLUME_HOLE_SLOTTED') else (ft[-1] if ft else F.types[0]))
                nlay = len(F['FEATURE_VOLUME_WITH_LAYOUT'][0]) if F.is_a('FEATURE_VOLUME_WITH_LAYOUT') else 1
                fstored[ftype] += nlay
                if ftype == 'FEATURE_VOLUME_HOLE_CIRCULAR':
                    Mf = m.a2p(E[fcs]['COORD_SYSTEM_CARTESIAN_3D'][-1])
                    if not (E[fcs].is_a('COORD_SYSTEM_CHILD') and E[fcs]['COORD_SYSTEM_CHILD'][0] == lpm['LOCATED_PART_MARKED'][3]):
                        rec['tags'].append(f'{OTHER_FEATURES_TAG}:hole_frame_not_part_frame'); fnot[ftype] += nlay; continue
                    cy, ev = hole_tools(m, Mf, F, thick)
                    tools += cy; exp_removed += ev; n_holes += nlay
                else:
                    rec['tags'].append(f'{OTHER_FEATURES_TAG}:{ftype[15:].lower()}'); fnot[ftype] += nlay
            if tools:
                lst = TopTools_ListOfShape(); [lst.Append(t_) for t_ in tools]
                args = TopTools_ListOfShape(); args.Append(body)
                cut = BRepAlgoAPI_Cut(); cut.SetArguments(args); cut.SetTools(lst); cut.SetRunParallel(False); cut.Build()
                if not cut.IsDone(): raise Unsupported('hole_boolean_failed')
                v0 = volume(body); res = cut.Shape(); v1 = volume(res)
                if solids_of(res) != 1 or v1 <= 0 or v1 > v0 + 1e-6:
                    res = body; v1 = v0
                # exactness check: every hole must remove pi r^2 x (plate thickness | stored depth)
                if abs((v0 - v1) - exp_removed) <= 0.02 * exp_removed:
                    body = res; fapplied['FEATURE_VOLUME_HOLE_CIRCULAR'] += n_holes; rec['holes'] = n_holes
                else:
                    rec['tags'].append(f'{OTHER_FEATURES_TAG}:hole_circular_volume_check_failed'); fnot['FEATURE_VOLUME_HOLE_CIRCULAR'] += n_holes
                    rec['hole_check'] = {'removed_mm3': round(v0 - v1, 1), 'expected_mm3': round(exp_removed, 1)}
            shape = place(body, W)
            ok = BRepCheck_Analyzer(shape).IsValid(); vol = volume(shape)
            rec.update(valid=bool(ok), volume_mm3=round(vol, 1), solids=solids_of(shape))
            if not ok or vol <= 0: rec['tags'].append('invalid_solid')
            rec['status'] = 'exact' if not rec['tags'] else ('approx' if all(t.startswith(('root_radius', 'corner_radius', 'camber', 'section_orientation')) for t in rec['tags']) else 'tagged')
            key = (lpm['LOCATED_PART_MARKED'][3], lpm['LOCATED_PART_MARKED'][4], round(vol, 1))
            dup_key = (lpm['LOCATED_PART_MARKED'][3], rec.get('mark'), round(vol, 1), tuple(round(x, 1) for x in (bbox(shape) or [])))
            if dup_key in seen_dups: rec['source_coincident_duplicate_of'] = seen_dups[dup_key]; n_dup += 1
            else: seen_dups[dup_key] = lpm.id
            v6 = sorted({'cis2-feature-not-applied' if t.startswith(OTHER_FEATURES_TAG) else 'cis2-camber-not-applied' if t.startswith('camber')
                         else 'cis2-approx-section' if t.startswith(('root_radius', 'corner_radius', 'section_orientation')) else 'cis2-invalid'
                         for t in rec['tags']})
            items.append((shape, f'cis2:{lpm.id}', rec['mark'], rec['cls'] + (f" [v6:{','.join(v6)}]" if v6 else '')))
            bb = bbox(shape); rec['bbox_mm'] = [round(x, 2) for x in bb] if bb else None
        except Unsupported as ex:
            rec = rec or {'lpm': lpm.id, 'mark': lpm['LOCATED_PART_MARKED'][1], 'tags': []}
            rec['status'] = 'not_built'; rec['tags'].append(f'not_built:{ex}'); fail[str(ex)] += 1
        except Exception as ex:
            rec = rec or {'lpm': lpm.id, 'mark': lpm['LOCATED_PART_MARKED'][1], 'tags': []}
            rec['status'] = 'not_built'; rec['tags'].append(f'error:{type(ex).__name__}:{str(ex)[:80]}'); fail[f'{type(ex).__name__}'] += 1
        for t in rec['tags']: tags_total[t.split(':')[0] + (':' + t.split(':')[1] if t.startswith(OTHER_FEATURES_TAG) else '')] += 1
        recs.append(rec)
    # bolts: stored positions, no head / nut geometry -> counted, not built
    nb = 0; njs = 0; bolt_kinds = collections.Counter()
    for e in E.values():
        if e.is_a('JOINT_SYSTEM_MECHANICAL'):
            njs += 1; a = e['JOINT_SYSTEM_MECHANICAL']; nb += len(a[4] or [])
            fm = E[a[5]] if isinstance(a[5], Ref) else None
            if fm is not None:
                for c in fm['FASTENER_MECHANISM'][5] or []:
                    bolt_kinds[E[c].types[0]] += 1
    st['bolts'] = {'joint_systems_mechanical': njs, 'bolt_positions_stored': nb, 'built': 0,
                   'reason': 'bolt positions and shank diameter / length are stored, head and nut geometry and the shank start are not: counted, not built',
                   'fastener_components': dict(bolt_kinds)}
    st['source_coincident_duplicates'] = n_dup     # parts stored twice or more at the same place with the same body (source content; written as stored)
    st['features'] = {'stored': dict(fstored), 'applied': dict(fapplied), 'not_applied': dict(fnot)}
    st['parts'] = {'stored': len(lpms), 'built': len(items), 'not_built': len(lpms) - len(items) if not limit else None,
                   'by_status': dict(collections.Counter(r['status'] for r in recs)), 'by_class': dict(collections.Counter(r.get('cls') for r in recs)),
                   'tags': dict(tags_total), 'not_built_reasons': dict(fail)}
    st['valid_solids'] = sum(1 for r in recs if r.get('valid')); st['invalid_solids'] = sum(1 for r in recs if r.get('valid') is False)
    bbs = [r['bbox_mm'] for r in recs if r.get('bbox_mm')]
    st['bbox_mm'] = [min(b[0] for b in bbs), min(b[1] for b in bbs), min(b[2] for b in bbs), max(b[3] for b in bbs), max(b[4] for b in bbs), max(b[5] for b in bbs)] if bbs else None
    if not items:
        return 4, dict(st, status='nothing_built')
    st['products_written'] = write_step(out, items)
    st['out_bytes'] = os.path.getsize(out); st['sec'] = round(time.time() - T0, 1)
    if parts_path:
        json.dump({'version': VERSION, 'parts': recs}, open(parts_path, 'w'))
    if census_path or src_parts_path:
        # source inventory in ifc_census format: every LOCATED_PART_MARKED is an expected part (gid = STEP PRODUCT id)
        cat = lambda r: 'member' if r.get('cls', '').startswith('PART_PRISMATIC') and r.get('section_type') in ('I_TYPE', 'CHANNEL', 'RECTANGLE_HOLLOW', 'CIRCLE_HOLLOW') else 'connection'
        if src_parts_path:
            with gzip.open(src_parts_path, 'wt') as g:
                for r in recs:
                    g.write(json.dumps({'gid': f"cis2:{r['lpm']}", 'cls': r.get('cls'), 'name': r.get('mark'), 'cat': cat(r), 'rt': ['CIS2'], 'cv': 3}) + '\n')
        if census_path:
            bc = collections.Counter(cat(r) for r in recs); bcl = collections.Counter(r.get('cls') for r in recs)
            json.dump({'schema': schema, 'census_version': 3, 'source_format': 'cis2_lpm6', 'products_total': len(lpms), 'expected_parts': len(recs),
                       'by_category': dict(bc), 'by_class': dict(bcl), 'length_unit_m': m.unit_mm / 1000.0}, open(census_path, 'w'))
    return 0, dict(st, status='ok')

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('src'); ap.add_argument('out'); ap.add_argument('--parts'); ap.add_argument('--census')
    ap.add_argument('--src-parts'); ap.add_argument('--limit', type=int)
    a = ap.parse_args()
    try:
        rc, st = convert(a.src, a.out, a.parts, a.census, a.src_parts, a.limit)
    except Exception as ex:
        import traceback; traceback.print_exc()
        rc, st = 3, {'status': 'error', 'error': f'{type(ex).__name__}: {ex}'}
    json.dump(st, open(a.out + '.stats.json', 'w'), indent=1) if rc in (0, 4) else None
    print(json.dumps(st)); sys.exit(rc)

if __name__ == '__main__':
    main()
