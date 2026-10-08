"""DB1 -> IFC -> STEP.

Decoded members (db1dec) are written as an IFC2X3 model of extrusions that uses
Tekla's own section definitions (harvested from 5,056 Tekla IFC exports) and
Tekla's own placement convention, then the team lead's ifc2step5.py (hybrid,
--prec 2) turns that IFC into AP214 faceted-brep STEP, exactly as for native IFC.

Placement (validated against Tekla IFC on 8.07/7.64): extrusion direction is
-x_raw of the part csys, profile X = x_raw cross y, profile Y = y; the extrusion
starts at the end that is NOT the stored origin when the part runs along +x_raw.
"""
import json, math, os, re, sys, time, collections, subprocess
import numpy as np
import ifcopenshell, ifcopenshell.guid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db1dec import decode, members, _axis_agreement, _axis_flags

# ------------------------------------------------------------------ sections
NUM = r'(\d+(?:\.\d+)?)'
P_PLATE2 = re.compile(r'^(?:PL|FL|FB|BL|PLT|FLT|PLATE|BPL|FPL|FLAT)\s*' + NUM + r'\s*[X\*x]\s*' + NUM + r'$')
P_PLATE1 = re.compile(r'^(?:PL|FL|FB|BL|PLT|FLT|PLATE|BPL|FPL)\s*' + NUM + r'$')
P_ROUND = re.compile(r'^(?:RB|D|ROD|RD|DIA)\s*' + NUM + r'$')
P_TUBE = re.compile(r'^(?:PD|PIPE|O|CHS|RO)\s*' + NUM + r'\s*[X\*x]\s*' + NUM + r'$')
P_BOLT = re.compile(r'^MM' + NUM + r'\*' + NUM)
P_RECT = re.compile(r'^' + NUM + r'\s*[\*X]\s*' + NUM + r'$')
P_SQBAR = re.compile(r'^(?:SQ|SB|SQB)\s*' + NUM + r'$')
P_SQBR2 = re.compile(r'^(?:SQBR|SQB|SQ)\s*' + NUM + r'\s*[X\*]\s*' + NUM + r'$')
P_DBA = re.compile(r'^(?:DBA|DEFORMED_BAR_ANCHOR|HAS|HSA)[_ ]?([\d/.-]+)"?\s*(?:DIA)?')
P_PLATE_ANY = re.compile(r'^(?:PL|FL|FB|BL|PLT|FLT|PLATE|BPL|FPL|FLAT|GRTG|GRATING)[\s\d.]')


_NAME_COL = re.compile(rb'(?<![\x21-\x7e])COLUMN\x00')
_NAME_BEAM = re.compile(rb'(?<![\x21-\x7e])BEAM\x00')


def _valid(kind, v):
    if kind in ('ARB', 'ARBV'):
        return isinstance(v, list) and len(v) >= 4
    need = {'I': 4, 'T': 4, 'U': 4, 'L': 3, 'C': 3, 'Z': 4, 'RHS': 3, 'CHS': 2, 'RECT': 2, 'CIRC': 1, 'AI': 4}.get(kind, 1)
    return isinstance(v, list) and len(v) >= need and all(x is not None and x > 0 for x in v[:need])


FRAC_RE = re.compile(r'^(\d+)(?:-(\d+)/(\d+))?$|^(\d+)/(\d+)$|^(\d*\.\d+)$')


def inch(tok):
    """'3/4' '1-1/4' '1' '.188' '0.625' -> inches"""
    m = FRAC_RE.match(tok.strip().rstrip('"'))
    if not m: return None
    if m.group(1): return int(m.group(1)) + (int(m.group(2)) / int(m.group(3)) if m.group(2) else 0)
    if m.group(4): return int(m.group(4)) / int(m.group(5))
    return float(m.group(6))


P_STUD = re.compile(r'^(?:STUD|NELSON_STUD|HSA|DBA|DEFORMED_BAR|DBAR|REBAR)[-_ ]?(\d+(?:-\d+/\d+)?|\d+/\d+|\d*\.\d+)(MM|M)?"?(?:-?DIA)?$')
P_WS = re.compile(r'^WS\s*(\d+(?:-\d+/\d+)?|\d+/\d+|\d*\.\d+)"?\s*X\s*[\d/.-]+"?$')          # weld stud <dia in>X<len in>
P_AT = re.compile(r'^(?:AT|ATR|ATRD)\s*' + NUM + r'$')                                          # all-thread rod, metric diameter
P_SQBAR3 = re.compile(r'^BAR\s*' + NUM + r'\s*[X\*]\s*' + NUM + r'$')
P_KTUBE = re.compile(r'^K' + NUM + r'/' + NUM + r'(?:/' + NUM + r')?$')                            # Dutch koker K<h>/<b>/<t> or K<a>/<t>
P_RHS3 = re.compile(r'^(?:RHS|SHS|CFRHS|HFRHS|CFSHS|HFSHS)\s*' + NUM + r'\s*[X\*]\s*' + NUM + r'\s*[X\*]\s*' + NUM + r'$')
P_SHS2 = re.compile(r'^(?:SHS|CFSHS|HFSHS)\s*' + NUM + r'\s*[X\*]\s*' + NUM + r'$')
P_OD = re.compile(r'^(?:OD|CFCHS|HFCHS|BUIS)\s*' + NUM + r'\s*[X\*]\s*' + NUM + r'$')
P_LMET = re.compile(r'^L' + NUM + r'\s*[X/\*]\s*' + NUM + r'\s*[X/\*]\s*' + NUM + r'$')
P_BPLT = re.compile(r'^(?:BPLT|CHKD_PLT|CHKPL)\s*' + NUM + r'\s*[X\*]\s*' + NUM + r'$')

P_AB = re.compile(r'^(?:AB|ANCHOR|ROD)' + NUM + r'$')
P_GRTG = re.compile(r'^(?:GRTG|GRATING|GR)\s*' + NUM + r'\s*[X\*x]\s*' + NUM + r'$')
P_HSSR = re.compile(r'^(?:HSS|TS)([\d.]+)X([\d.]+)X([\d./]+)$')
P_HSSC = re.compile(r'^(?:HSS|TS)([\d.]+)X([\d./]+)$')
# z3: older Tekla naming seen on 6.87 / 7.01 models (MoldTek-era)
P_CHAN_BR = re.compile(r'^\[\s*' + NUM + r'\s*\*\s*' + NUM + r'\s*\*\s*' + NUM + r'\s*\*\s*' + NUM + r'$')   # [h*b*tw*tf channel
P_UEUR = re.compile(r'^U\s*(\d{2,3})$')                                                                    # U160 = DIN 1026 / UPN160
P_TUBE2 = re.compile(r'^TUBE\s*' + NUM + r'\s*[X\*]\s*' + NUM + r'$')                                       # TUBE d*t
P_L2 = re.compile(r'^L\s*' + NUM + r'\s*[X\*]\s*' + NUM + r'$')                                              # L a*t equal angle (catalog L40*3 = 40x40x3)
P_NOSIZE = re.compile(r'^(?:R\.B|RB|F\.B|FB|FL|PL|D|ROD|PIPE|TUBE|L|U|C|I|\[)\s*\.?\s*$')


def _section_for_raw(name, cat):
    """-> (kind, params, source) or (None, reason, None)"""
    if not name: return None, 'no_profile', None
    n0 = name.strip().upper()
    # Plate-family names carry their own size (or are contour plates with their own outline);
    # the harvested catalog holds per-INSTANCE plate outlines under such names, so never use it.
    platey = bool(P_PLATE_ANY.match(n0))
    e = None if platey else cat.get(name)
    if e:
        v = e.get('dims') if 'dims' in e else e.get('pts')
        if _valid(e['kind'], v): return e['kind'], v, 'catalog'
    n = name.strip().upper()
    m = P_PLATE2.match(n)
    if m:  # beam-type plate: thickness first, width second (IFC XDim=t, YDim=b)
        t, b = float(m.group(1)), float(m.group(2))
        return 'RECT', [t, b], 'parametric'
    m = P_ROUND.match(n)
    if m: return 'CIRC', [float(m.group(1)) / 2], 'parametric'
    m = P_SQBAR.match(n)
    if m: return 'RECT', [float(m.group(1)), float(m.group(1))], 'parametric'
    m = P_SQBR2.match(n)
    if m: return 'RECT', [float(m.group(1)), float(m.group(2))], 'parametric_square_bar'
    m = P_DBA.match(n)
    if m and inch(m.group(1).rstrip('-')): return 'CIRC', [inch(m.group(1).rstrip('-')) * 25.4 / 2], 'parametric_anchor'
    m = P_TUBE.match(n)
    if m:
        d, t = float(m.group(1)), float(m.group(2))
        return ('CHS', [d / 2, t], 'parametric') if t < d / 2 else ('CIRC', [d / 2], 'parametric')
    if P_BOLT.match(n):
        # a bolt GROUP (MM<d>*<len>/...): the record's axis is the group layout line, not a
        # bolt, so an extrusion along it would be wrong geometry. Excluded until bolt
        # positions are decoded from the group pattern.
        return None, 'bolt_group_excluded', None
    m = P_GRTG.match(n)
    if m: return 'RECT', [float(m.group(1)), float(m.group(2))], 'parametric_grating'
    m = P_STUD.match(n)
    if m and m.group(2):                      # STUD_19M-DIA: metric diameter
        try: return 'CIRC', [float(m.group(1)) / 2], 'parametric_stud_shank'
        except ValueError: pass
    elif m and inch(m.group(1)): return 'CIRC', [inch(m.group(1)) * 25.4 / 2], 'parametric_stud_shank'
    m = P_WS.match(n)
    if m and inch(m.group(1)): return 'CIRC', [inch(m.group(1)) * 25.4 / 2], 'parametric_stud_shank'
    m = P_AT.match(n)
    if m: return 'CIRC', [float(m.group(1)) / 2], 'parametric_anchor'
    m = P_SQBAR3.match(n)
    if m and abs(float(m.group(1)) - float(m.group(2))) < 1e-6: return 'RECT', [float(m.group(1)), float(m.group(2))], 'parametric_square_bar'
    m = P_KTUBE.match(n) or P_RHS3.match(n) or P_SHS2.match(n)
    if m:
        g = [float(x) for x in m.groups() if x is not None]
        a, b, t = (g[0], g[1], g[2]) if len(g) == 3 else (g[0], g[0], g[1])
        if 0 < t < min(a, b) / 2:
            ro = 2 * t if t <= 6 else (2.5 * t if t <= 10 else 3 * t)     # EN 10219 corner radii
            return 'RHS', [b, a, t, ro - t, ro], 'parametric_rhs'          # catalog convention: XDim=b, YDim=a
    m = P_OD.match(n)
    if m:
        d, t = float(m.group(1)), float(m.group(2))
        if 0 < t < d / 2: return 'CHS', [d / 2, t], 'parametric'
    m = P_LMET.match(n)
    if m:
        a, b, t = (float(x) for x in m.groups())
        if 0 < t < min(a, b): return 'L', [a, b, t, t], 'parametric_angle'   # catalog order [leg1, leg2, t, r]
    m = P_BPLT.match(n)
    if m: return 'RECT', [float(m.group(1)), float(m.group(2))], 'parametric'
    m = P_AB.match(n)
    if m: return 'CIRC', [float(m.group(1)) / 2], 'parametric_anchor'
    m = P_HSSR.match(n)
    if m and all(inch(g) for g in m.groups()):
        raw = [inch(g) for g in m.groups()]
        k = 25.4 if max(raw) <= 30 else 1.0           # the largest HSS is 20 in: bigger numbers are mm
        a, b, tw = (x * k for x in raw)
        return 'RHS', [b, a, tw, tw, 2 * tw], 'parametric_hss'      # catalog convention: XDim=b, YDim=a, r_in=t, r_out=2t
    m = P_HSSC.match(n)
    if m and all(inch(g) for g in m.groups()):
        raw = [inch(g) for g in m.groups()]
        k = 25.4 if max(raw) <= 30 else 1.0
        d, tw = (x * k for x in raw)
        return 'CHS', [d / 2, tw], 'parametric_hss_round'
    m = P_RECT.match(n)
    if m: return 'RECT', [float(m.group(2)), float(m.group(1))], 'parametric_panel'
    n2 = re.sub(r'^F\.\s*B\.?\s*', 'FB', n)
    if n2 != n:
        m = P_PLATE2.match(n2)
        if m: return 'RECT', [float(m.group(1)), float(m.group(2))], 'parametric_flat_bar'
    m = P_CHAN_BR.match(n)
    if m:
        h, b, tw, tf = (float(x) for x in m.groups())
        if 0 < tw < b and 0 < tf < h / 2: return 'U', [h, b, tw, tf], 'parametric_channel'
    m = P_UEUR.match(n)
    if m and cat.get('UPN' + m.group(1)):
        e = cat['UPN' + m.group(1)]
        v = e.get('dims')
        if _valid(e['kind'], v): return e['kind'], v, 'catalog_upn_alias'
    m = P_TUBE2.match(n)
    if m:
        d, t = float(m.group(1)), float(m.group(2))
        if 0 < t < d / 2: return 'CHS', [d / 2, t], 'parametric_tube'
    m = P_L2.match(n)
    if m:
        a, t = float(m.group(1)), float(m.group(2))
        if 0 < t < a: return 'L', [a, a, t, t], 'parametric_angle_equal'
    if P_PLATE1.match(n): return None, 'contour_plate', None
    if P_NOSIZE.match(n): return None, 'profile_without_size', None
    return None, 'unresolved', None


def _nums(v):
    out = []
    for x in (v if isinstance(v, (list, tuple)) else [v]):
        if isinstance(x, (list, tuple)): out += _nums(x)
        elif isinstance(x, (int, float)): out.append(float(x))
    return out


def _plausible(kind, v, how, name=''):
    """a name parsed into an absurd size is not a section ('RB8534.4' is 28 ft, not an 8.5 m round
    bar, and hangs the tessellator). Catalog sections are real; plates/panels only reject absurd
    values (Tekla contour plates of 400+ mm and 330 mm square blocks are modelled objects)."""
    if how == 'catalog': return True
    n = (name or '').strip().upper()
    try:
        if kind == 'CIRC':
            d = 2 * v[0]
            if how == 'parametric_stud_shank': lim = 100
            elif how == 'parametric_anchor': lim = 150
            elif re.match(r'^(RB|ROD|RD|DIA)', n): lim = 300          # round bars
            else: lim = 1500                                           # D-prefixed rounds / disks
            return 0 < d <= lim
        if kind == 'CHS': return 0 < 2 * v[0] <= 3000 and 0 < v[1] < v[0]
        if kind == 'RECT': return all(0 < x <= 50000 for x in v[:2])
        if kind == 'RHS': return 0 < v[0] <= 2000 and 0 < v[1] <= 2000 and 0 < v[2]
        if kind == 'L': return 0 < v[0] <= 1000 and 0 < v[1] <= 1000 and 0 < v[2]
        return all(abs(x) <= 50000 for x in _nums(v))
    except Exception:
        return False


def section_for(name, cat):
    """-> (kind, params, source) or (None, reason, None); implausible sizes -> 'implausible_profile'"""
    kind, v, how = _section_for_raw(name, cat)
    if kind is not None and not _plausible(kind, v, how, name):
        return None, 'implausible_profile', None
    return kind, v, how


def part_cat(prof, how):
    """z3 grading category of a decoded Tekla part: member | connection (plates, contour plates, bolt groups, studs,
    anchors) | other (grating)"""
    n = (prof or '').strip().upper()
    if how in ('parametric_grating',) or n.startswith(('GRTG', 'GRATING')):
        return 'other'
    if how in ('contour_plate', 'contour_plate_no_outline', 'bolt_group_excluded', 'parametric_stud_shank', 'parametric_anchor') \
            or P_PLATE_ANY.match(n) or P_BOLT.match(n) or P_PLATE1.match(n):
        return 'connection'
    return 'member'


# ------------------------------------------------------------------ IFC writer
class IfcOut:
    def __init__(self, name):
        f = self.f = ifcopenshell.file(schema='IFC2X3')
        self.o3 = f.createIfcCartesianPoint((0., 0., 0.))
        self.o2 = f.createIfcCartesianPoint((0., 0.))
        self.p2 = f.createIfcAxis2Placement2D(self.o2, None)
        self.z = f.createIfcDirection((0., 0., 1.))
        units = f.createIfcUnitAssignment([
            f.createIfcSIUnit(None, 'LENGTHUNIT', 'MILLI', 'METRE'),
            f.createIfcSIUnit(None, 'PLANEANGLEUNIT', None, 'RADIAN')])
        wcs = f.createIfcAxis2Placement3D(self.o3, None, None)
        self.ctx = f.createIfcGeometricRepresentationContext(None, 'Model', 3, 1e-5, wcs, None)
        oh = f.createIfcOwnerHistory(
            f.createIfcPersonAndOrganization(f.createIfcPerson(None, None, 'db1step'), f.createIfcOrganization(None, 'db1step', None, None, None), None),
            f.createIfcApplication(f.createIfcOrganization(None, 'db1step', None, None, None), '1.0', 'db1step', 'db1step'),
            None, 'ADDED', None, None, None, int(time.time()))
        self.oh = oh
        self.proj = f.createIfcProject(ifcopenshell.guid.new(), oh, name, None, None, None, None, [self.ctx], units)
        site_pl = f.createIfcLocalPlacement(None, wcs)
        self.site = f.createIfcSite(ifcopenshell.guid.new(), oh, 'site', None, None, site_pl, None, None, 'ELEMENT', None, None, None, None, None)
        f.createIfcRelAggregates(ifcopenshell.guid.new(), oh, None, None, self.proj, [self.site])
        self.site_pl = site_pl
        self.elems = []; self.prof = {}

    def profile(self, name, kind, v):
        key = (name, kind)
        if key in self.prof: return self.prof[key]
        f = self.f; p2 = self.p2; nm = name or kind
        g = lambda i, d=None: (v[i] if i < len(v) and v[i] is not None else d)
        if kind == 'I':
            p = f.createIfcIShapeProfileDef('AREA', nm, p2, g(0), g(1), g(2), g(3), g(4))
        elif kind == 'T':
            p = f.createIfcTShapeProfileDef('AREA', nm, p2, g(0), g(1), g(2), g(3), g(4), g(5), g(6), g(7), g(8), None)
        elif kind == 'U':
            p = f.createIfcUShapeProfileDef('AREA', nm, p2, g(0), g(1), g(2), g(3), g(4), g(5), g(6), None)
        elif kind == 'L':
            p = f.createIfcLShapeProfileDef('AREA', nm, p2, g(0), g(1), g(2), g(3), g(4), g(5), None, None)
        elif kind == 'C':
            p = f.createIfcCShapeProfileDef('AREA', nm, p2, g(0), g(1), g(2), g(3), g(4), None)
        elif kind == 'Z':
            p = f.createIfcZShapeProfileDef('AREA', nm, p2, g(0), g(1), g(2), g(3), g(4), g(5))
        elif kind == 'RHS':
            p = f.createIfcRectangleHollowProfileDef('AREA', nm, p2, g(0), g(1), g(2), g(3), g(4))
        elif kind == 'CHS':
            p = f.createIfcCircleHollowProfileDef('AREA', nm, p2, g(0), g(1))
        elif kind == 'RECT':
            p = f.createIfcRectangleProfileDef('AREA', nm, p2, g(0), g(1))
        elif kind == 'CIRC':
            p = f.createIfcCircleProfileDef('AREA', nm, p2, g(0))
        elif kind == 'AI':
            p = f.createIfcAsymmetricIShapeProfileDef('AREA', nm, p2, g(0), g(1), g(2), g(3), g(4), g(5), g(6), g(7), None)
        elif kind in ('ARB', 'ARBV'):
            pts = [f.createIfcCartesianPoint((float(x), float(y))) for x, y in v]
            if pts and v[0] != v[-1]: pts.append(pts[0])
            p = f.createIfcArbitraryClosedProfileDef('AREA', nm, f.createIfcPolyline(pts))
        else:
            return None
        self.prof[key] = p
        return p

    def member(self, m, kind, v, cls='IfcBeam'):
        f = self.f
        xr, y = m['xr'], m['y']
        start = m['O'] + (m['xr'] * m['L'] if m['sgn'] == 1 else 0)
        zdir = -xr
        xdir = np.cross(xr, y)
        pl = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint(tuple(float(c) for c in start)),
                                         f.createIfcDirection(tuple(float(c) for c in zdir)),
                                         f.createIfcDirection(tuple(float(c) for c in xdir)))
        lp = f.createIfcLocalPlacement(self.site_pl, pl)
        prof = self.profile(m['prof'], kind, v)
        if prof is None: return None
        solid = f.createIfcExtrudedAreaSolid(prof, f.createIfcAxis2Placement3D(self.o3, None, None), self.z, float(m['L']))
        rep = f.createIfcShapeRepresentation(self.ctx, 'Body', 'SweptSolid', [solid])
        e = getattr(f, 'create' + cls)(ifcopenshell.guid.new(), self.oh, m.get('prof') or 'part', None, None, lp,
                                         f.createIfcProductDefinitionShape(None, None, [rep]), None)
        self.elems.append(e)
        return e

    def plate(self, m, poly, thick):
        """contour plate: outline (u,v) in the plane of (x, y) through O, extruded +/- t/2."""
        f = self.f
        u = m['x']; v = m['y']; nrm = np.cross(u, v); nrm = nrm / np.linalg.norm(nrm)
        start = m['O'] - nrm * thick / 2
        pl = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint(tuple(float(c) for c in start)),
                                         f.createIfcDirection(tuple(float(c) for c in nrm)),
                                         f.createIfcDirection(tuple(float(c) for c in u)))
        lp = f.createIfcLocalPlacement(self.site_pl, pl)
        pts = [f.createIfcCartesianPoint((float(a), float(b))) for a, b in poly] 
        pts.append(pts[0])
        prof = f.createIfcArbitraryClosedProfileDef('AREA', m['prof'], f.createIfcPolyline(pts))
        solid = f.createIfcExtrudedAreaSolid(prof, f.createIfcAxis2Placement3D(self.o3, None, None), self.z, float(thick))
        rep = f.createIfcShapeRepresentation(self.ctx, 'Body', 'SweptSolid', [solid])
        e = f.createIfcPlate(ifcopenshell.guid.new(), self.oh, m['prof'], None, None, lp,
                             f.createIfcProductDefinitionShape(None, None, [rep]), None)
        self.elems.append(e)
        return e

    def plate_points(self, name, p3, thick):
        """plate from 3D outline points (old engines): Newell plane, extrude +/- t/2."""
        f = self.f
        P = np.array(p3); n = np.zeros(3)
        for i in range(len(P)):
            a, b = P[i], P[(i + 1) % len(P)]
            n += np.array([(a[1] - b[1]) * (a[2] + b[2]), (a[2] - b[2]) * (a[0] + b[0]), (a[0] - b[0]) * (a[1] + b[1])])
        if np.linalg.norm(n) < 1e-9: return None
        n /= np.linalg.norm(n)
        eu = np.array([1., 0, 0]) if abs(n[0]) < 0.9 else np.array([0., 1, 0]); eu = eu - n * (n @ eu); eu /= np.linalg.norm(eu)
        ev = np.cross(n, eu); c = P.mean(0)
        pl = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint(tuple(float(x) for x in (c - n * thick / 2))),
                                         f.createIfcDirection(tuple(float(x) for x in n)), f.createIfcDirection(tuple(float(x) for x in eu)))
        lp = f.createIfcLocalPlacement(self.site_pl, pl)
        pts = [f.createIfcCartesianPoint((float((q - c) @ eu), float((q - c) @ ev))) for q in P]; pts.append(pts[0])
        prof = f.createIfcArbitraryClosedProfileDef('AREA', name, f.createIfcPolyline(pts))
        solid = f.createIfcExtrudedAreaSolid(prof, f.createIfcAxis2Placement3D(self.o3, None, None), self.z, float(thick))
        rep = f.createIfcShapeRepresentation(self.ctx, 'Body', 'SweptSolid', [solid])
        e = f.createIfcPlate(ifcopenshell.guid.new(), self.oh, name, None, None, lp, f.createIfcProductDefinitionShape(None, None, [rep]), None)
        self.elems.append(e); return e

    # ---- frames: (origin, Z, X) in world; solids are built in the local frame of a frame
    def _p3(self, frame):
        f = self.f; o, Z, X = frame
        return f.createIfcAxis2Placement3D(f.createIfcCartesianPoint(tuple(float(c) for c in o)),
                                           f.createIfcDirection(tuple(float(c) for c in Z)),
                                           f.createIfcDirection(tuple(float(c) for c in X)))

    @staticmethod
    def member_frame(m):
        xr, y = m['xr'], m['y']
        return (m['O'] + (xr * m['L'] if m['sgn'] == 1 else 0), -xr, np.cross(xr, y))

    @staticmethod
    def plate_frame(m, thick):
        u = m['x']; v = m['y']; n = np.cross(u, v); n = n / np.linalg.norm(n)
        return (m['O'] - n * thick / 2, n, u)

    def extrusion(self, prof, depth, rel=None):
        pos = self._p3(rel) if rel is not None else self.f.createIfcAxis2Placement3D(self.o3, None, None)
        return self.f.createIfcExtrudedAreaSolid(prof, pos, self.z, float(depth))

    def poly_profile(self, name, poly):
        f = self.f
        pts = [f.createIfcCartesianPoint((float(a), float(b))) for a, b in poly]; pts.append(pts[0])
        return f.createIfcArbitraryClosedProfileDef('AREA', name, f.createIfcPolyline(pts))

    @staticmethod
    def relative(parent, child):
        op, Zp, Xp = parent; Yp = np.cross(Zp, Xp); R = np.stack([Xp, Yp, Zp], 1)
        oc, Zc, Xc = child
        return (R.T @ (oc - op), R.T @ Zc, R.T @ Xc)

    SNAP = 1e-3     # rad (~0.06 deg): a cut axis this close to one of the part's own axes is taken as exact

    @staticmethod
    def _snap(v, tol):
        v = np.asarray(v, float); v = v / np.linalg.norm(v); i = int(np.argmax(np.abs(v)))
        if np.sqrt(max(0.0, 1.0 - v[i] * v[i])) < tol:
            w = np.zeros(3); w[i] = 1.0 if v[i] > 0 else -1.0; return w
        return v

    def cut_frame(self, parent, child):
        """cut frame relative to the part; axes within SNAP of the part's axes are snapped exactly onto them.
        Tekla stores cuts that are square to the part with float noise (0.0002 rad seen); a cut face that is
        0.01 deg off a flange face makes OpenCASCADE's boolean loop for hours, while the snapped cut moves
        the face by < 0.1 mm per 100 mm."""
        o, Z, X = self.relative(parent, child)
        Z = self._snap(Z, self.SNAP)
        X = np.asarray(X, float) - np.dot(X, Z) * Z; X = self._snap(X / np.linalg.norm(X), self.SNAP)
        if abs(np.dot(X, Z)) > 1e-9: X = X - np.dot(X, Z) * Z; X = X / np.linalg.norm(X)
        return (o, Z, X)

    def element(self, cls, name, frame, prof, depth, cuts=()):
        """cuts: [(frame, prof, depth)] subtracted from the solid (IfcBooleanResult DIFFERENCE)."""
        f = self.f
        solid = self.extrusion(prof, depth); rtype = 'SweptSolid'
        for cf, cp, cd in cuts:
            solid = f.createIfcBooleanResult('DIFFERENCE', solid, self.extrusion(cp, cd, self.cut_frame(frame, cf)))
            rtype = 'CSG'
        rep = f.createIfcShapeRepresentation(self.ctx, 'Body', rtype, [solid])
        e = getattr(f, 'create' + cls)(ifcopenshell.guid.new(), self.oh, name or 'part', None, None,
                                         f.createIfcLocalPlacement(self.site_pl, self._p3(frame)),
                                         f.createIfcProductDefinitionShape(None, None, [rep]), None)
        self.elems.append(e)
        return e

    def bolt_group(self, name, bolts):
        """z3: one IfcMechanicalFastener per Tekla bolt group: per bolt a shank (circle d, from -L/2 to +L/2 along the
        group z axis), a hex head (across flats 1.6 d, height 0.65 d) and a hex nut (0.8 d) - the owner's BuildBolt geometry"""
        f = self.f
        items = []
        for b in bolts:
            d, L = b['d'], b['L']
            key = ('BOLT_SHANK_D%g' % d, 'CIRC')
            shank = self.profile(key[0], 'CIRC', [d / 2])
            R = 1.6 * d / math.sqrt(3.0)
            hexpts = [(R * math.cos(math.pi / 6 + i * math.pi / 3), R * math.sin(math.pi / 6 + i * math.pi / 3)) for i in range(6)]
            hexp = self.prof.get(('BOLT_HEX_D%g' % d, 'ARB'))
            if hexp is None:
                hexp = self.profile('BOLT_HEX_D%g' % d, 'ARB', hexpts)
            c, ez, ex = b['c'], b['ez'], b['ex']
            for start, prof, depth in ((c - ez * L / 2, shank, L), (c - ez * (L / 2 + 0.65 * d), hexp, 0.65 * d), (c + ez * L / 2, hexp, 0.8 * d)):
                pos = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint(tuple(float(x) for x in start)),
                                                  f.createIfcDirection(tuple(float(x) for x in ez)), f.createIfcDirection(tuple(float(x) for x in ex)))
                items.append(f.createIfcExtrudedAreaSolid(prof, pos, self.z, float(depth)))
        rep = f.createIfcShapeRepresentation(self.ctx, 'Body', 'SweptSolid', items)
        e = f.createIfcMechanicalFastener(ifcopenshell.guid.new(), self.oh, name or 'bolt', None, None,
                                          f.createIfcLocalPlacement(self.site_pl, f.createIfcAxis2Placement3D(self.o3, None, None)),
                                          f.createIfcProductDefinitionShape(None, None, [rep]), None, None, None)
        self.elems.append(e)
        return e

    def write(self, path):
        f = self.f
        if self.elems:
            f.createIfcRelContainedInSpatialStructure(ifcopenshell.guid.new(), self.oh, None, None, self.elems, self.site)
        f.write(path)


def convert(db1_path, out_ifc, cat, layout=None, variants=(), allow_full=True):
    """-> stats dict (+ arc_stats: contours processed, contours with runs of arc points, outlines refused
    because they would cross themselves); writes out_ifc when at least one member resolves."""
    import db1dec as _dd
    for k in _dd.ARC_STATS: _dd.ARC_STATS[k] = 0
    st = _convert(db1_path, out_ifc, cat, layout, variants, allow_full)
    if isinstance(st, dict): st['arc_stats'] = dict(_dd.ARC_STATS); st['arc_writer'] = 'arc2'
    return st


def _convert(db1_path, out_ifc, cat, layout=None, variants=(), allow_full=True):
    t0 = time.time()
    data = open(db1_path, 'rb').read()
    import gzip as _gz
    truncated = False
    if data[:2] == b'\x1f\x8b':
        try: data = _gz.decompress(data)
        except EOFError:
            import zlib; data = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(data); truncated = True
    ban = re.search(rb'(\d+\.\d+)', data[:16]); engine = float(ban.group(1)) if ban else 0.0
    if 0 < engine < 7.5:
        return convert_old(data, out_ifc, cat, engine, t0)
    small = len(data) < 20_000_000          # full discovery is cheap on small files
    db, pts, cs, lay = decode(data, layout, variants, allow_full or small)
    st = dict(layout=lay, decode_sec=round(time.time() - t0, 1), mb=round(db.L / 1e6, 2), truncated_source=truncated)
    if not lay or lay.get('csys') is None:
        if (lay or {}).get('status_hint') == 'needs_full_discovery':
            st['status'] = 'deferred_layout'
        elif (small and not any(len(r) >= 3 and s >= 45 for s, r in db.runs if s in (65, 73))) or len(data) < 1_000_000:
            st['status'] = 'empty_model'      # no part records at all: a template / blank model
        else:
            st['status'] = 'no_member_layout'
        return st
    M = members(db, pts, cs, lay)
    st['members'] = len(M)
    ag = _axis_agreement(db, pts, lay, M)
    st['axis_agreement'] = round(ag, 4) if ag is not None else None
    if ag is not None and ag < 0.9:
        # the orientation link does not put member x along the member's own reference line:
        # hold the model back rather than write wrong geometry
        st['status'] = 'suspect_orientation'
        return st
    # attribute-link sanity: parts whose attribute record names them COLUMN stand vertical
    # (100% on every validated model); a wrong part->attribute link scatters names at random
    kind = {}; cols = cv = beams = bh = 0
    for m in M:
        if m.get('cut') or m.get('attr') is None or not m['prof']: continue
        a = m['attr']
        if a not in kind:
            rr = db.attr_records(lay, a)
            txt = db.b[rr[0]:rr[0] + lay['attr_stride']].upper() if rr else b''
            # the exact part name, not substrings ('COLUMN_LINE_BEAM' is a beam)
            kind[a] = 'col' if _NAME_COL.search(txt) else ('beam' if _NAME_BEAM.search(txt) else None)
        if kind[a] == 'col':
            sec = section_for(m['prof'], cat)[0]
            if sec in (None, 'RECT'): continue          # cap/base plates carry the column's name
            cols += 1; cv += abs(m['x'][2]) > 0.9
        elif kind[a] == 'beam': beams += 1; bh += abs(m['x'][2]) < 0.1
    st['name_check'] = dict(columns=cols, col_vertical=round(cv / cols, 3) if cols else None,
                            beams=beams, beam_flat=round(bh / beams, 3) if beams else None)
    if cols >= 20 and cv / cols < 0.7:
        st['status'] = 'suspect_attr_link'
        return st
    # member-level orientation check: a part whose csys x does not lie along its own reference
    # line would be drawn pointing the wrong way -> not written (counted)
    flags = _axis_flags(db, pts, lay, M)
    bad_axis = sum(1 for f in flags if not f)
    if bad_axis:
        M = [m for m, f in zip(M, flags) if f]
    st['axis_mismatch_dropped'] = bad_axis
    out = IfcOut(os.path.basename(db1_path))
    why = collections.Counter(); src = collections.Counter(); unres = collections.Counter()
    links = db.find_cut_links(M)
    st['cut_layout'] = getattr(db, 'cut_layout', None)

    def body(m):
        """-> (frame, profile_entity, depth, kind_label) or (None, reason)"""
        kind, v, how = section_for(m['prof'], cat)
        if kind is None and v == 'contour_plate':
            poly = db.polygon(lay, m)
            thick = float(re.findall(r'[\d.]+', m['prof'])[0])
            if not 0 < thick <= 50000: return (None, 'implausible_profile')
            if poly and thick > 0:
                return (out.plate_frame(m, thick), out.poly_profile(m['prof'], poly), thick, 'contour_plate')
            return (None, 'contour_plate_no_outline')
        if kind is None: return (None, v)
        prof = out.profile(m['prof'], kind, v)
        if prof is None: return (None, 'writer_skip')
        return (out.member_frame(m), prof, m['L'], how)

    cut_body = {}
    for m in M:
        if m.get('cut'):
            b = body(m)
            if b[0] is not None: cut_body[m['seq']] = b[:3]
            else: why['cut_body_unbuilt'] += 1
    applied = 0
    plist = []          # z3: one record per decoded part: [seq, profile, category, status, how/reason, GlobalId, n_cuts]
    for m in M:
        if m.get('cut'):
            why['cut_part_excluded'] += 1; continue
        b = body(m)
        if b[0] is None:
            why[b[1]] += 1; unres[m['prof'] or '<none>'] += 1
            plist.append([m.get('seq'), m.get('prof'), part_cat(m.get('prof'), b[1]), 'skipped', b[1], None, 0]); continue
        cuts = [cut_body[c] for c in links.get(m['seq'], []) if c in cut_body]
        applied += len(cuts)
        cat_ = part_cat(m.get('prof'), b[3])
        cls = 'IfcPlate' if cat_ in ('connection', 'other') and b[3] not in ('parametric_stud_shank', 'parametric_anchor') else (
              'IfcMechanicalFastener' if b[3] in ('parametric_stud_shank', 'parametric_anchor') else 'IfcBeam')
        e = out.element(cls, m['prof'], b[0], b[1], b[2], cuts)
        plist.append([m.get('seq'), m.get('prof'), cat_, 'written', b[3], e.GlobalId, len(cuts)])
        src[b[3]] += 1
    st['parts_list'] = plist
    st['cuts_applied'] = applied
    # sanity: in real steel models most horizontal beams stand web-vertical; a wrongly
    # decoded orientation table would scatter these
    hz = [m for m in M if not m.get('cut') and abs(m['x'][2]) < 0.1 and m['L'] > 500]
    yv = sum(1 for m in hz if abs(m['y'][2]) > 0.996) / len(hz) if hz else None
    # web orientation only means something for I/H sections (angles, pipes, rods, purlins do not
    # stand web-vertical): judge the orientation link on horizontal I-sections
    hzI = [m for m in hz if section_for(m['prof'], cat)[0] == 'I']
    yvI = sum(1 for m in hzI if abs(m['y'][2]) > 0.996) / len(hzI) if hzI else None
    st.update(written=len(out.elems), sources=dict(src), skipped=dict(why), horizontal=len(hz),
              y_vertical_frac=round(yv, 3) if yv is not None else None, horizontal_I=len(hzI),
              y_vertical_frac_I=round(yvI, 3) if yvI is not None else None,
              unresolved_top=unres.most_common(25), secs=round(time.time() - t0, 1))
    if len(hzI) >= 50 and yvI < 0.2:
        # real steel models stand most beams web-vertical; a near-zero share means the
        # orientation link is wrong -> hold the model back rather than write wrong geometry
        st['status'] = 'suspect_orientation'
        return st
    if out.elems:
        out.write(out_ifc)
        st['status'] = 'ok'
    else:
        st['status'] = 'no_resolvable_members'
    return st


def convert_old(data, out_ifc, cat, engine, t0):
    import db1old
    M, info, cut_rel = db1old.read(data, engine)
    bad_axis = sum(1 for m in M if m.get('axis_ok') is False)
    M = [m for m in M if m.get('axis_ok') is not False]
    st = dict(layout={'engine': engine, 'format': 'old', **info}, decode_sec=round(time.time() - t0, 1), mb=round(len(data) / 1e6, 2), members=len(M),
              axis_mismatch_dropped=bad_axis)
    out = IfcOut(os.path.basename(out_ifc))
    why = collections.Counter(); src = collections.Counter(); unres = collections.Counter()

    def old_plate_frame(m, thick):
        """old engines: outline points in the part csys (z used when form_type == 2);
        plane from Newell, frame origin at the outline centroid offset by -t/2."""
        xr, y = m['xr'], m['y']; z = np.cross(xr, y); useZ = m.get('form') == 2
        p3 = [m['O'] + xr * q[0] + y * q[1] + (z * q[2] if useZ else 0) for q in m['old_poly']]
        cl = []
        for q in p3:
            if not cl or np.linalg.norm(cl[-1] - q) > 1e-6: cl.append(q)
        if len(cl) > 1 and np.linalg.norm(cl[0] - cl[-1]) < 1e-6: cl.pop()
        if len(cl) < 3: return None
        P = np.array(cl); n = np.zeros(3)
        for i in range(len(P)):
            a, b = P[i], P[(i + 1) % len(P)]
            n += np.array([(a[1] - b[1]) * (a[2] + b[2]), (a[2] - b[2]) * (a[0] + b[0]), (a[0] - b[0]) * (a[1] + b[1])])
        if np.linalg.norm(n) < 1e-9: return None
        n /= np.linalg.norm(n)
        eu = np.array([1., 0, 0]) if abs(n[0]) < 0.9 else np.array([0., 1, 0]); eu = eu - n * (n @ eu); eu /= np.linalg.norm(eu)
        ev = np.cross(n, eu); c = P.mean(0)
        return (c - n * thick / 2, n, eu), [((q - c) @ eu, (q - c) @ ev) for q in P]

    def body(m):
        if m.get('bolt'): return (None, 'bolt_group_excluded')
        kind, v, how = section_for(m['prof'], cat)
        if kind is None and v == 'contour_plate':
            thick = float(re.findall(r'[\d.]+', m['prof'])[0])
            if not 0 < thick <= 50000: return (None, 'implausible_profile')
            if m.get('old_poly') and len(m['old_poly']) >= 3 and thick > 0:
                r = old_plate_frame(m, thick)
                if r:
                    REGION[id(m)] = (r[1], [])
                    return (r[0], out.poly_profile(m['prof'], r[1]), thick, 'contour_plate')
            return (None, 'contour_plate_no_outline')
        if kind is None: return (None, v)
        prof = out.profile(m['prof'], kind, v)
        if prof is not None and BOLTS_ON:
            REGION[id(m)] = db1bolts.outline(kind, v)
        return (out.member_frame(m), prof, m['L'], how) if prof is not None else (None, 'writer_skip')

    REGION = {}
    import db1bolts
    eng_s = '%.2f' % engine
    BOLTS_ON = os.environ.get('DB1_BOLTS', '1') == '1' and eng_s in db1bolts.BOLT_ENGINES
    BL = []
    if BOLTS_ON:
        for m in M:
            if m.get('bolt') and not m.get('cut'):
                for b in db1bolts.bolts_of(m):
                    BL.append(b)
    HI = db1bolts.HoleIndex(BL)
    hole_prof = {}
    holes_cut = 0; parts_holes_skipped = 0; ply = []

    cut_body = {}
    for m in M:
        if m.get('cut'):
            b = body(m)
            if b[0] is not None: cut_body[m['pid']] = b[:3]
            else: why['cut_body_unbuilt'] += 1
    applied = 0
    plist = []
    for m in M:
        if m.get('cut'): why['cut_part_excluded'] += 1; continue
        if BOLTS_ON and m.get('bolt'):
            bl = db1bolts.bolts_of(m)
            if bl:
                e = out.bolt_group(m.get('prof'), bl)
                plist.append([m.get('pid'), m.get('prof'), 'connection', 'written', 'bolt_group', e.GlobalId, 0]); src['bolt_group'] += 1
                continue
        b = body(m)
        if b[0] is None:
            why[b[1]] += 1; unres[m['prof'] or '<none>'] += 1
            plist.append([m.get('pid'), m.get('prof'), part_cat(m.get('prof'), b[1]), 'skipped', b[1], None, 0]); continue
        cuts = [cut_body[c] for c in cut_rel.get(m['pid'], []) if c in cut_body]
        applied += len(cuts)
        if BOLTS_ON and BL:
            reg = REGION.get(id(m))
            if reg is None:
                # no exact section outline: test against nothing, count bolts whose shank meets the part's box
                pass
            else:
                for i in HI.holes_for(b[0], b[2], reg):
                    bb = BL[i]; dh = bb['d'] + db1bolts.clearance(bb['d'])
                    key = round(dh, 2)
                    if key not in hole_prof:
                        hole_prof[key] = out.profile('BOLT_HOLE_D%g' % key, 'CIRC', [dh / 2])
                    cuts = cuts + [((bb['c'] - bb['ez'] * bb['L'] / 2, bb['ez'], bb['ex']), hole_prof[key], bb['L'])]
                    holes_cut += 1
                    if len(ply) < 400:
                        sp = db1bolts.ply_check(b[0], b[2], reg, bb)
                        if sp: ply.append((sp[0] + bb['L'] / 2, bb['L'] / 2 - sp[1], bb['d']))
        cat_ = part_cat(m.get('prof'), b[3])
        cls = 'IfcPlate' if cat_ in ('connection', 'other') and b[3] not in ('parametric_stud_shank', 'parametric_anchor') else (
              'IfcMechanicalFastener' if b[3] in ('parametric_stud_shank', 'parametric_anchor') else 'IfcBeam')
        e = out.element(cls, m['prof'], b[0], b[1], b[2], cuts)
        plist.append([m.get('pid'), m.get('prof'), cat_, 'written', b[3], e.GlobalId, len(cuts)])
        src[b[3]] += 1
    st['parts_list'] = plist
    hz = [m for m in M if not m.get('cut') and abs(m['x'][2]) < 0.1 and m['L'] > 500]
    yv = sum(1 for m in hz if abs(m['y'][2]) > 0.996) / len(hz) if hz else None
    hzI = [m for m in hz if m.get('prof') and section_for(m['prof'], cat)[0] == 'I']
    yvI = sum(1 for m in hzI if abs(m['y'][2]) > 0.996) / len(hzI) if hzI else None
    if BOLTS_ON:
        hit = sum(1 for h in HI.hits if h > 0)
        inside = sum(1 for a_, b_, d_ in ply if a_ >= -0.5 and b_ >= -0.5)
        st['bolt_stats'] = {'groups': src.get('bolt_group', 0), 'bolts': len(BL), 'holes_cut': holes_cut,
                            'bolts_with_holed_part': hit, 'bolts_without_holed_part': len(BL) - hit,
                            'plies_checked': len(ply), 'plies_within_shank': inside,
                            'writer': 'db1bolts (port of tekla-step-pipeline BuildBolt) + clearance holes'}
    st.update(written=len(out.elems), sources=dict(src), skipped=dict(why), horizontal=len(hz), cuts_applied=applied,
              y_vertical_frac=round(yv, 3) if yv is not None else None, horizontal_I=len(hzI),
              y_vertical_frac_I=round(yvI, 3) if yvI is not None else None,
              unresolved_top=unres.most_common(25), secs=round(time.time() - t0, 1))
    if len(hzI) >= 50 and yvI < 0.2:
        st['status'] = 'suspect_orientation'; return st
    ag = info.get('axis_agreement')
    if ag is not None and ag < 0.9:
        # member csys x not along the member's own reference line: wrong table, hold back
        st['status'] = 'suspect_orientation'; return st
    if out.elems:
        out.write(out_ifc); st['status'] = 'ok'
    else:
        st['status'] = 'no_resolvable_members' if M else 'no_member_layout'
    return st
