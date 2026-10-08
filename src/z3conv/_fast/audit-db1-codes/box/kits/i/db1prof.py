"""db1prof: profile fixes for Tekla DB1 -> STEP (data-3 class-2 reasons "profile catalog entries" / "profile sizes missing" /
"angle: root radius assumed = t"). Every definition comes from the model's own data; nothing is guessed.

1. Tapered parametric profiles (Tekla built-in grammar, verified on the model's own Tekla report):
     ELD h1*b1*h2*b2     solid, section h1 x b1 at the part start point -> h2 x b2 at the end point
     EPD h1*b1*h2*b2*t   the same as a tube of wall thickness t
   Verified on 1620-C-003 (KSS_ASSEMBLY_LIST-AREA.CSV, Tekla's own weights/areas):
     ELD2188*2188*1260*1260 L1500 -> 28,132 kg / 13.51 m2 (solid frustum: 28,150 kg / 13.51 m2; a constant
     2188x1260 ellipse would be 25,500 kg / 12.6 m2); ELD5288*5288*2212*2212 L7150 -> 654,237 kg (frustum 654,700).
   Start/end orientation: the start (h1) end sits at the part start point (verified by diameter continuity:
   1640-C-001 D4594 | ELD4594..3268 | D3268 | ELD3268..2248 | D2248 stacks end to end).
   Only circular sections (h1 == b1 and h2 == b2) are written; elliptical ones stay unresolved.
   Written as an exact-volume faceted frustum (polygon radii scaled so each end polygon has the circle's area).
2. Model catalog (per model sha256, from the model folder's own profdb.bin): see profdb.py / model_catalogs.json.
3. Old engines (< 7.5): profile names may hold Latin-1 characters ('R.B \\xd820' = 'R.B Ø20'); the old reader cut
   the name at the first non-ASCII byte ('R.B ') -> 'profile_without_size'. latin1_cstr keeps them.
4. Old-engine records with zero length at the origin and no outline carry no geometry ('/110/-10.04/1/110/0/19.91',
   '5', '0*5955'): not parts (is_null_record).
"""
import math, re
import numpy as np

NUM = r'(\d+(?:\.\d+)?)'
P_ELD = re.compile(r'^ELD\s*' + NUM + r'\s*\*\s*' + NUM + r'\s*\*\s*' + NUM + r'\s*\*\s*' + NUM + r'$')
P_EPD = re.compile(r'^EPD\s*' + NUM + r'\s*\*\s*' + NUM + r'\s*\*\s*' + NUM + r'\s*\*\s*' + NUM + r'\s*\*\s*' + NUM + r'$')
MAX_D = 6000.0          # largest tapered section accepted (data: 5288 mm vessel dummies)


class Frustum:
    """circular frustum (solid when t == 0, tube otherwise): d1 at the part start point, d2 at the end point"""
    __slots__ = ('d1', 'd2', 't', 'name')

    def __init__(self, d1, d2, t, name=None):
        self.d1, self.d2, self.t, self.name = float(d1), float(d2), float(t), name


def parse_tapered(n):
    """-> (kind, params, how) or None. FRUSTUM params [d1, d2, t]; constant sections collapse to CIRC / CHS."""
    m = P_ELD.match(n)
    if m:
        h1, b1, h2, b2 = (float(x) for x in m.groups())
        if abs(h1 - b1) > 1e-6 or abs(h2 - b2) > 1e-6: return None, 'elliptic_section_unsupported', None
        if not (0 < h1 <= MAX_D and 0 < h2 <= MAX_D): return None, 'implausible_profile', None
        if abs(h1 - h2) < 1e-6: return 'CIRC', [h1 / 2], 'parametric_eld'
        return 'FRUSTUM', [h1, h2, 0.0], 'parametric_eld'
    m = P_EPD.match(n)
    if m:
        h1, b1, h2, b2, t = (float(x) for x in m.groups())
        if abs(h1 - b1) > 1e-6 or abs(h2 - b2) > 1e-6: return None, 'elliptic_section_unsupported', None
        if not (0 < h1 <= MAX_D and 0 < h2 <= MAX_D and t > 0): return None, 'implausible_profile', None
        if 2 * t >= min(h1, h2):                                   # wall fills the narrow end: no bore there
            return None, 'implausible_profile', None
        if abs(h1 - h2) < 1e-6: return 'CHS', [h1 / 2, t], 'parametric_epd'
        return 'FRUSTUM', [h1, h2, t], 'parametric_epd'
    return None


def plausible_frustum(v):
    d1, d2, t = v
    return 0 < d1 <= MAX_D and 0 < d2 <= MAX_D and t >= 0 and (t == 0 or 2 * t < min(d1, d2))


def nseg(r, tol=0.5):
    """polygon segments for chord error <= tol mm (24..256)"""
    if r <= tol: return 24
    return int(min(256, max(24, math.ceil(math.pi / math.acos(max(-1.0, 1 - tol / r))))))


def frustum_solid(f, fr, depth):
    """IfcFacetedBrep of a frustum in the element's local frame (z = 0 .. depth along the extrusion axis).
    fr: Frustum with radii given at z=0 (r0) and z=depth (r1) already resolved by the caller."""
    r0o, r1o, t = fr.d1 / 2, fr.d2 / 2, fr.t
    n = nseg(max(r0o, r1o))
    k = math.sqrt(2 * math.pi / (n * math.sin(2 * math.pi / n)))      # equal-area polygon
    ang = [2 * math.pi * i / n for i in range(n)]

    def ring(r, z):
        return [f.createIfcCartesianPoint((float(r * k * math.cos(a)), float(r * k * math.sin(a)), float(z))) for a in ang]

    def face(pts):
        return f.createIfcFace([f.createIfcFaceOuterBound(f.createIfcPolyLoop(pts), True)])

    A = ring(r0o, 0.0); B = ring(r1o, depth)
    faces = []
    if t <= 0:
        faces.append(face(list(reversed(A)))); faces.append(face(B))
        for i in range(n):
            j = (i + 1) % n
            faces.append(face([A[i], A[j], B[j], B[i]]))
    else:
        Ai = ring(r0o - t, 0.0); Bi = ring(r1o - t, depth)
        for i in range(n):
            j = (i + 1) % n
            faces.append(face([A[i], A[j], B[j], B[i]]))          # outer wall (outward)
            faces.append(face([Ai[j], Ai[i], Bi[i], Bi[j]]))      # inner wall (facing the bore)
            faces.append(face([A[j], A[i], Ai[i], Ai[j]]))        # bottom annulus (facing -z)
            faces.append(face([B[i], B[j], Bi[j], Bi[i]]))        # top annulus (facing +z)
    return f.createIfcFacetedBrep(f.createIfcClosedShell(faces))


def frustum_volume(d1, d2, t, L):
    def v(a, b): return math.pi * L / 12 * (a * a + a * b + b * b)
    return v(d1, d2) - (v(d1 - 2 * t, d2 - 2 * t) if t > 0 else 0.0)


def oriented(fr, m):
    """radii at local z=0 / z=L of db1step.member_frame(m): the frame starts at the end that is NOT the stored origin
    when sgn == 1 (extrusion along -x_raw); Tekla's start point (h1) is the stored-origin end (sgn chosen so x points
    from the origin towards p2)."""
    if m.get('sgn', 1) == 1:
        return Frustum(fr.d2, fr.d1, fr.t, fr.name)
    return Frustum(fr.d1, fr.d2, fr.t, fr.name)


def latin1_cstr(b, o, n):
    """old-engine string field: printable ASCII and Latin-1 letters (0xA0-0xFF, e.g. 0xD8 'Ø'); stops at NUL / control"""
    e = b.find(b'\0', o, o + n)
    s = b[o:e if e >= 0 else o + n]
    out = []
    for c in s:
        if c < 32 or 126 < c < 160: break
        out.append(chr(c))
    return ''.join(out)


def is_null_record(m):
    """old-engine record without any geometry: zero length, origin exactly (0,0,0), no outline points"""
    try:
        return float(m.get('L') or 0) == 0.0 and not m.get('old_poly') and all(float(c) == 0.0 for c in m['O'])
    except Exception:
        return False
