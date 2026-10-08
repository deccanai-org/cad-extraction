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
import db1prof  # db1prof-patch

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


_PANEL_AXB_EXACT = [False]          # code v: set per model by _convert from the engine banner (DB1_PANEL_AXB_ENGINES)


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
        # cut-not-applied P15: Tekla takes the smaller dimension as the thickness whatever the order ('PL177.8*9.525' = 'PL9.525*177.8'):
        # IRON_ORE 7.24 vs its own Tekla IFC: the 14 'PL a*b' parts with a > b stood rotated 90 deg (bbox y/z swapped), the 328 with
        # a < b matched; the holes and cuts of those plates were cut through the wrong face
        return 'RECT', [min(t, b), max(t, b)], 'parametric'
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
    if m:
        # code v: a square A*A section has no orientation to assume (both axes carry A): exact, not a stand-in. A*B (A != B) keeps the
        # 'orientation assumed' tag (Tekla IFC truth: too few GUID-joined panels to validate A = height along the part y)
        if abs(float(m.group(1)) - float(m.group(2))) < 1e-9 and os.environ.get('DB1_PANEL_SQUARE_EXACT', '1') == '1':
            return 'RECT', [float(m.group(2)), float(m.group(1))], 'parametric_rect_square'
        # code v: A*B = Tekla's concrete 'h*b' (A = height along the part y). Tekla IFC truth (GUID join, mesh extents in the writer frame):
        # 140 / 140 non-square A*B parts with A along y, 0 rotated (7 models, 7.64 / 7.82 / 8.07 / 8.53), writer y axis = Tekla's on catalog
        # I sections 7,642 / 7,643 on the same engines -> exact on those engines; other engines keep the tag (no GUID-joined truth)
        if _PANEL_AXB_EXACT[0]:
            return 'RECT', [float(m.group(2)), float(m.group(1))], 'parametric_rect_hb'
        return 'RECT', [float(m.group(2)), float(m.group(1))], 'parametric_panel'
    # cut-not-applied P9: 'R.B \xd820' (R.B + Latin-1 O-slash + 20) / 'R.B 20' / 'R.BD20' (Latin-1 names kept by db1prof) is a round bar of the stated diameter (the name
    # carries the full section). Unresolved before: steel round bars dropped, and the 7.01 operative rung-hole cutters 'R.B \xd820'
    # (obj_type 11, P4) left cut_body_unbuilt (4fa8f263: 30, cc9bf730: 47).
    n3 = re.sub('^R\\.\\s*B\\.?\\s*(?:\u00d8|DIA\\.?|D)?\\s*', 'RB', n)
    if n3 != n:
        m = P_ROUND.match(n3)
        if m: return 'CIRC', [float(m.group(1)) / 2], 'parametric'
    n2 = re.sub(r'^F\.\s*B\.?\s*', 'FB', n)
    if n2 != n:
        m = P_PLATE2.match(n2)
        if m:
            # cut-not-applied P8: 'F.B 75X10' is width x thickness; the thickness lies across the part (XDim, local z) like 'PL t*b'.
            # Proof: Tekla's net weight of the e151a8fa ladder stringers F.B 75X10 (48.0 net / 48.7 gross kg) = 29 D21 rung holes
            # through 10 mm; with [75, 10] the same holes ran through 75 mm (45.3 kg); toe plates F.B 75X6 lay flat.
            a_, b_ = float(m.group(1)), float(m.group(2))
            return 'RECT', [min(a_, b_), max(a_, b_)], 'parametric_flat_bar'
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
    tp = db1prof.parse_tapered(n)  # db1prof-patch
    if tp: return tp
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
            elif how == 'parametric_eld': lim = db1prof.MAX_D  # db1prof-patch
            elif how == 'parametric_anchor': lim = 150
            elif re.match(r'^(RB|ROD|RD|DIA)', n): lim = 300          # round bars
            else: lim = 1500                                           # D-prefixed rounds / disks
            return 0 < d <= lim
        if kind == 'CHS': return 0 < 2 * v[0] <= (db1prof.MAX_D if how == 'parametric_epd' else 3000) and 0 < v[1] < v[0]
        if kind == 'FRUSTUM': return db1prof.plausible_frustum(v)  # db1prof-patch
        if kind == 'RECT': return all(0 < x <= 50000 for x in v[:2])
        if kind == 'RHS': return 0 < v[0] <= 2000 and 0 < v[1] <= 2000 and 0 < v[2]
        if kind == 'L': return 0 < v[0] <= 1000 and 0 < v[1] <= 1000 and 0 < v[2]
        return all(abs(x) <= 50000 for x in _nums(v))
    except Exception:
        return False


# cut-not-applied P6: cut parts (ANTIMATERIAL / BlOpCl CUTPART) made by polygon cuts can carry their depth as a bare number instead of
# 'BL<t>' (component-made cuts '111.600', '469.000'; 8.53 '914.4' / '1016' / '1219.2' through 18-20 in pipes). The outline is the
# part's own contour record and a contour part's profile is its thickness, so they are built exactly like 'BL<t>' cuts.
P_CUTDEPTH = re.compile(r'^\d+(?:\.\d+)?$')
PART_CUTS_ON = os.environ.get('DB1_PART_CUTS', '1') == '1'     # cut-not-applied P7, diagnostics only: '0' writes every part uncut


def zero_section(prof):
    """cut-not-applied P10: a cut part whose own profile has a zero dimension ('PL0*177.8' on the 7.24 models) subtracts nothing:
    counted as cut_body_zero_thickness, not as an unapplied cut"""
    n = (prof or '').strip().upper()
    m = P_PLATE2.match(n) or P_PLATE1.match(n) or P_ROUND.match(n)
    return bool(m) and any(float(g) == 0.0 for g in m.groups() if g is not None)


def section_for(name, cat):
    """-> (kind, params, source) or (None, reason, None); implausible sizes -> 'implausible_profile'"""
    kind, v, how = _section_for_raw(name, cat)
    if kind is not None and not _plausible(kind, v, how, name):
        return None, 'implausible_profile', None
    return kind, v, how


APPROX_SOURCES = {
    'parametric_angle': 'root radius assumed = t (not in the profile name)',
    'parametric_angle_equal': 'equal-leg angle read from L a*t; root radius assumed = t',
    'parametric_rhs': 'corner radii from the EN 10219 rule (not in the profile name)',
    'parametric_hss': 'corner radii assumed 2t (not in the profile name)',
    'catalog_upn_alias': 'U<n> read as the DIN 1026 / UPN<n> catalog section',
    'parametric_grating': 'bar grating written as a solid plate',
    'parametric_stud_shank': 'stud written as its shank only (no head)',
    'parametric_panel': 'panel read from an AxB name (orientation assumed)',
}


def section_radius(kind, v):
    """cut-not-applied P13: a radius that bounds the section around the member axis (full height / width, so profile offsets are
    covered too); only sizes the extension of an oblique fitting, the half-space then clips the exact end"""
    try:
        if kind in ('CIRC', 'CHS'): return float(v[0])
        if kind == 'FRUSTUM': return max(float(v[0]), float(v[1])) / 2
        nums = [abs(float(c)) for c in _nums(v)]
        return float(math.hypot(*sorted(nums)[-2:])) if len(nums) >= 2 else 1000.0
    except Exception:
        return 1000.0


def fit_old_plan(m, fits, lcuts, kind, v):
    """cut-not-applied P13 (old engines) -> (member to write, [(point, n_out)] half-spaces, notes). A Tekla fitting moves the part end
    to the fitting plane (shortens or lengthens the part); the side away from the part middle is removed. Perpendicular planes: the end
    is moved exactly (no boolean). Oblique planes: the end is extended past the plane by R tan(angle) + 1 mm and clipped by the plane.
    Line cuts remove the +normal side, except end cuts (axis crossing in the outer quarters) whose normal points at the part middle:
    there the end side is removed. Contour plates, polybeams and fitting planes within ~6 deg of the axis: half-spaces only."""
    O, x, L = m['O'], m['x'], m['L']; mid = O + x * L / 2
    t0, t1 = 0.0, L; hs = []; notes = collections.Counter(); ends = collections.Counter()
    ext_ok = kind is not None and len(m.get('old_poly') or []) < 3
    R = section_radius(kind, v)
    for P, n in fits:
        n_out = n if float((mid - P) @ n) < 0 else -n
        c = float(n_out @ x)
        if not ext_ok or abs(c) < 0.1:
            hs.append((P, n_out)); notes['halfspace_only'] += 1; continue
        tp = float((P - O) @ n_out) / c
        perp = abs(abs(c) - 1) < 1e-6
        m_ = 0.0 if perp else R * math.sqrt(max(0.0, 1 - c * c)) / abs(c) + 1.0
        if c > 0: t1 = tp + m_; ends['end'] += 1; longer = tp > L + 1e-6
        else: t0 = tp - m_; ends['start'] += 1; longer = tp < -1e-6
        if not perp: hs.append((P, n_out))
        notes['perpendicular' if perp else 'oblique'] += 1; notes['lengthened' if longer else 'shortened'] += 1
    notes['same_end_twice'] += sum(1 for k_, n_ in ends.items() if n_ > 1)
    for P, n in lcuts:
        n = np.asarray(n, float); c = float(n @ x)
        tp = float((P - O) @ n) / c if abs(c) > 0.1 else None
        if float((mid - P) @ n) > 0 and tp is not None and (tp < 0.25 * L or tp > 0.75 * L):
            # an END cut whose stored normal points at the part middle: the end side is removed (0762effe L50*50*6 25281 carries the
            # same end plane twice with opposite normals; '+normal removed' deleted the whole part, Tekla's net weight 2.4 kg).
            # Cuts along the part or through its middle keep '+normal removed' (GSK 7.24: 8 HSS4X4X5/16 halved lengthwise).
            n = -n; notes['line_cut_end_normal_flipped'] += 1
        hs.append((P, n)); notes['line_cut'] += 1
    uniq = {}
    for P, n in hs: uniq.setdefault((round(float(P @ n), 2),) + tuple(np.round(n, 5)), (P, n))
    notes['halfspaces_deduplicated'] += len(hs) - len(uniq); hs = list(uniq.values())
    if t1 - t0 <= 1.0:
        notes['degenerate_kept_as_recorded'] += 1; return m, [], notes
    if abs(t0) < 1e-9 and abs(t1 - L) < 1e-9: return m, hs, notes
    return dict(m, O=O + x * t0, E=O + x * t1, L=float(t1 - t0)), hs, notes


def approx_name(prof, how):
    why = APPROX_SOURCES.get(how)
    return f'{prof} [approx: {why}]' if why else prof


def part_cat(prof, how):
    """z3 grading category of a decoded Tekla part: member | connection (plates, contour plates, bolt groups, studs,
    anchors) | other (grating)"""
    n = (prof or '').strip().upper()
    if how == 'no_profile':
        return 'connection'           # Tekla 7.5+/8.x: bolt groups are member records without a profile name (counted as expected parts)
    if how == 'holes_only_group':
        return 'feature'              # holes only (no bolt solid in the model): not a physical part
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
        elif kind == 'RRECT':                                   # tekla-slots: slotted bolt hole (XDim, YDim, corner radius)
            p = f.createIfcRoundedRectangleProfileDef('AREA', nm, p2, g(0), g(1), g(2))
        elif kind == 'AI':
            p = f.createIfcAsymmetricIShapeProfileDef('AREA', nm, p2, g(0), g(1), g(2), g(3), g(4), g(5), g(6), g(7), None)
        elif kind == 'FRUSTUM':  # db1prof-patch
            p = db1prof.Frustum(v[0], v[1], v[2], nm)
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
        if isinstance(prof, db1prof.Frustum):  # db1prof-patch
            solid = db1prof.frustum_solid(f, prof, depth); rtype = 'Brep'
        else:
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

    def element_arc(self, cls, name, arc, prof, cuts=()):
        """arc patch: section revolved about the arc's centre axis (exact curved beam), then the cuts (frames relative to the start frame)"""
        f = self.f; frame0 = arc['frame']
        ax = f.createIfcAxis1Placement(f.createIfcCartesianPoint(tuple(float(c) for c in arc['loc'])), f.createIfcDirection(tuple(float(c) for c in arc['dir'])))
        solid = f.createIfcRevolvedAreaSolid(prof, f.createIfcAxis2Placement3D(self.o3, None, None), ax, float(arc['angle']))
        for cf, cp, cd in cuts:
            solid = f.createIfcBooleanResult('DIFFERENCE', solid, self.extrusion(cp, cd, self.cut_frame(frame0, cf)))
        rep = f.createIfcShapeRepresentation(self.ctx, 'Body', 'CSG' if cuts else 'SweptSolid', [solid])
        e = getattr(f, 'create' + cls)(ifcopenshell.guid.new(), self.oh, name or 'part', None, None,
                                         f.createIfcLocalPlacement(self.site_pl, self._p3(frame0)),
                                         f.createIfcProductDefinitionShape(None, None, [rep]), None)
        self.elems.append(e)
        return e

    def element_poly(self, cls, name, frame0, segs, prof, cuts=()):
        """audit P5: polybeam = union of mitred segment extrusions in the frame of the first segment, then the cuts"""
        f = self.f; solid = None
        for sg in segs:
            ex = self.extrusion(prof, sg['depth'], self.relative(frame0, sg['frame']))
            for pt, nrm, keep_pos in sg['clips']:
                o_l, n_l, _x = self.relative(frame0, (pt, nrm, _perp(nrm)))
                ex = f.createIfcBooleanClippingResult('DIFFERENCE', ex, f.createIfcHalfSpaceSolid(f.createIfcPlane(self._p3((o_l, n_l, _perp(n_l)))), bool(keep_pos)))
            solid = ex if solid is None else f.createIfcBooleanResult('UNION', solid, ex)
        for cf, cp, cd in cuts:
            solid = f.createIfcBooleanResult('DIFFERENCE', solid, self.extrusion(cp, cd, self.cut_frame(frame0, cf)))
        rep = f.createIfcShapeRepresentation(self.ctx, 'Body', 'CSG', [solid])
        e = getattr(f, 'create' + cls)(ifcopenshell.guid.new(), self.oh, name or 'part', None, None,
                                         f.createIfcLocalPlacement(self.site_pl, self._p3(frame0)),
                                         f.createIfcProductDefinitionShape(None, None, [rep]), None)
        self.elems.append(e)
        return e

    def bolt_group(self, name, bolts):
        """z3: one IfcMechanicalFastener per Tekla bolt group, closed outward-oriented IfcFacetedBrep polyhedra (exact, no kernel tessellation).
        Decoded placement (old-engine f6 / f10): head on the +z face, underside at f6 + f10/2 (+ head washer), shank toward -z for L,
        nut-side washers and nuts below the grip (counts from the assembly flags). Otherwise the Windows pipeline's centred shank with the
        head on -z. Head / nut from the standard table when the grade + diameter decode, else nominal (1.6d, 0.65d / 0.8d)."""
        f = self.f
        items = []

        def prism(base, ez, ex, ey, h, rad, k, a0, r_in=None):
            ring = [base + rad * (math.cos(a0 + 2 * math.pi * i / k) * ex + math.sin(a0 + 2 * math.pi * i / k) * ey) for i in range(k)]
            P = [f.createIfcCartesianPoint(tuple(float(x) for x in q)) for q in ring]
            Q = [f.createIfcCartesianPoint(tuple(float(x) for x in (q + ez * h))) for q in ring]
            if r_in:
                ri = [base + r_in * (math.cos(2 * math.pi * i / k) * ex + math.sin(2 * math.pi * i / k) * ey) for i in range(k)]
                Pi = [f.createIfcCartesianPoint(tuple(float(x) for x in q)) for q in ri]
                Qi = [f.createIfcCartesianPoint(tuple(float(x) for x in (q + ez * h))) for q in ri]
                faces = [f.createIfcFace([f.createIfcFaceOuterBound(f.createIfcPolyLoop(list(reversed(P))), True), f.createIfcFaceBound(f.createIfcPolyLoop(Pi), True)]),
                         f.createIfcFace([f.createIfcFaceOuterBound(f.createIfcPolyLoop(Q), True), f.createIfcFaceBound(f.createIfcPolyLoop(list(reversed(Qi))), True)])]
                for i in range(k):
                    j = (i + 1) % k
                    faces.append(f.createIfcFace([f.createIfcFaceOuterBound(f.createIfcPolyLoop([P[i], P[j], Q[j], Q[i]]), True)]))
                    faces.append(f.createIfcFace([f.createIfcFaceOuterBound(f.createIfcPolyLoop([Pi[j], Pi[i], Qi[i], Qi[j]]), True)]))
            else:
                faces = [f.createIfcFace([f.createIfcFaceOuterBound(f.createIfcPolyLoop(list(reversed(P))), True)]),
                         f.createIfcFace([f.createIfcFaceOuterBound(f.createIfcPolyLoop(Q), True)])]
                for i in range(k):
                    j = (i + 1) % k
                    faces.append(f.createIfcFace([f.createIfcFaceOuterBound(f.createIfcPolyLoop([P[i], P[j], Q[j], Q[i]]), True)]))
            items.append(f.createIfcFacetedBrep(f.createIfcClosedShell(faces)))
        import db1bolts as _db
        for b in bolts:
            d, L = b['d'], b['L']
            c, ez, ex = np.asarray(b['c'], float), np.asarray(b['ez'], float), np.asarray(b['ex'], float)
            ey = np.cross(ez, ex)
            n = 16
            r_sh = d / 2 * math.sqrt(2 * math.pi / (n * math.sin(2 * math.pi / n)))          # polygon area = circle area
            sg = b.get('std')
            if sg:
                Rh, hh, Rn, hn = sg['head_af'] / math.sqrt(3.0), sg['head_h'], sg['nut_af'] / math.sqrt(3.0), sg['nut_h']
            else:
                Rh, hh, Rn, hn = 1.6 * d / math.sqrt(3.0), 0.65 * d, 1.6 * d / math.sqrt(3.0), 0.8 * d
            prism(c - ez * L / 2, ez, ex, ey, L, r_sh, n, 0.0)                                  # shank
            if b.get('head_up'):
                top = c + ez * L / 2
                prism(top, ez, ex, ey, hh, Rh, 6, math.pi / 6)                                  # head above the shank top
                pt = c - ez * (b['zh'] - L / 2)                                                 # the bolt's polygon point (group z = 0)
                wod, wt = _db.washer_dims(b)
                if b.get('wash_head'):
                    prism(pt + ez * b['grip'][1], ez, ex, ey, wt, wod / 2, n, 0.0, r_in=(d + 1.0) / 2)
                z = b['grip'][0]
                for _ in range((b.get('wash_nut') or 0) + (b.get('wash_2') or 0)):
                    prism(pt + ez * (z - wt), ez, ex, ey, wt, wod / 2, n, 0.0, r_in=(d + 1.0) / 2); z -= wt
                for _ in range(max(1, b.get('nuts') or 1) if b.get('nuts', 1) else 0):
                    prism(pt + ez * (z - hn), ez, ex, ey, hn, Rn, 6, math.pi / 6); z -= hn
            else:
                prism(c - ez * (L / 2 + hh), ez, ex, ey, hh, Rh, 6, math.pi / 6)                # head below (Windows pipeline convention)
                prism(c + ez * L / 2, ez, ex, ey, hn, Rn, 6, math.pi / 6)                       # nut above
        rep = f.createIfcShapeRepresentation(self.ctx, 'Body', 'Brep', items)
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


def _no_native_parts(db):
    """v2 (eng): True when no known point table exists under the normal or the flag-1 record variant and the part-record
    strides hold fewer than 50 records"""
    from db1dec import Db
    for flags in ((4,), (1, 4, 5)):
        d = db
        if flags != (4,):
            d = Db(db.b); d.SEG_FLAGS = flags; d.PLAUS_MAX = d.GEO_MAX; d.segment()
        if len(d.bystride.get(73, ())) >= 50 or len(d.bystride.get(65, ())) >= 50: return False
        for st_, k_ in ((41, 17), (33, 9)):
            if d.find_points(fixed=(st_, k_)): return False
    return True


def convert(db1_path, out_ifc, cat, layout=None, variants=(), allow_full=True):
    """-> stats dict (+ arc_stats: contours processed, contours with runs of arc points, outlines refused
    because they would cross themselves); writes out_ifc when at least one member resolves."""
    import db1dec as _dd
    for k in _dd.ARC_STATS: _dd.ARC_STATS[k] = 0
    st = _convert(db1_path, out_ifc, cat, layout, variants, allow_full)
    if isinstance(st, dict): st['arc_stats'] = dict(_dd.ARC_STATS); st['arc_writer'] = 'arc2'
    return st


def _c1_name(prefix, tags, limit=120):
    # c1audit-stats: STEP PRODUCT names are cut at 120 characters (ifc2step6 step_str): the [approx: ...] marker must survive the cut
    # (code k: long family strings pushed it past 120 -> step_check approx_products missed it), and exact groups get no marker at all
    # (codes c-k wrote '[approx: ]' on every old-engine bolt group, exact or not)
    prefix = ' '.join(str(prefix or '').split())
    if not tags:
        return prefix[:limit]
    tag = '[approx: ' + '; '.join(tags) + ']'
    if len(tag) > limit - 10:
        tag = tag[:limit - 11] + ']'
    return (prefix[:max(0, limit - len(tag) - 1)].rstrip() + ' ' + tag).strip()


def _c1_slot(bb):
    # c1audit-stats: the bolt's group stores a slot length (old-engine string fields 1 / 2; htr kits carry bb['slot'])
    sl = bb.get('slot')
    if sl is None:
        p = (bb.get('_prof') or '').split('/')
        try:
            sl = (float(p[1]), float(p[2]))
        except (IndexError, ValueError):
            sl = (0.0, 0.0)
    return any(abs(float(x)) > 1e-9 for x in sl)


def _c1_v2_stats(bgroups, BG, holes_cut, holes_tol, db1bolts):
    # c1audit-stats: v2 bolt_stats in the keys build_index.classify_db1 reads
    BL2 = [bb for g in bgroups for bb in (BG.get(g['seq']) or [])]
    sl = {g['seq']: bool((g.get('slot_parts') or 0) and ((g.get('slot_x') or 0) > 0 or (g.get('slot_y') or 0) > 0)) for g in bgroups}
    W = lambda bb: (bb.get('wash_head') or 0) + (bb.get('wash_nut') or 0) + (bb.get('wash_2') or 0)
    live = [bb for bb in BL2 if not bb.get('holes_only')]
    return dict(bolts=len(BL2), standard_table_geometry=sum(1 for bb in BL2 if bb.get('std')),
                nominal_head_nut_bolts=sum(1 for bb in BL2 if not bb.get('std')),
                nominal_head_nut_written=sum(1 for bb in live if not bb.get('std')),
                holes_nominal_clearance=holes_cut - holes_tol, holes_only_bolts=len(BL2) - len(live),
                washers=sum(W(bb) for bb in live), washers_nominal=sum(W(bb) for bb in live if not db1bolts.washer_exact(bb)),
                washer_side_inferred=sum(1 for bb in live if bb.get('wash_2')),
                bolts_shifted_to_plies=sum(1 for bb in live if bb.get('head_up') and not bb.get('axial_decoded')),
                bolts_axial_unknown=sum(1 for bb in live if not bb.get('head_up')),
                slotted_bolts_cut_round=sum(1 for bb in BL2 if sl.get(bb.get('pid'))),
                model_catalog_bolts=sum(1 for bb in BL2 if (bb.get('std') or {}).get('source') == 'model_catalog'),
                tekla_env_catalog=sum(1 for bb in BL2 if (bb.get('std') or {}).get('catalog_scope') == 'environment'))   # code r (owner 18:10Z)


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
    _PANEL_AXB_EXACT[0] = bool(ban) and ban.group(1).decode() in os.environ.get('DB1_PANEL_AXB_ENGINES', '7.64,7.82,8.07,8.53').split(',')   # code v
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
        elif _no_native_parts(db):
            # v2 (eng): no point table and (almost) no part records under ANY record variant: the model holds only
            # reference models / drawings (8.07 'STAIR COORDINATION': 4 stride-73 records, 0 points, 26 RM layers)
            st['status'] = 'empty_model'; st['empty_reason'] = 'no native part records (reference models / drawings only)'
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
        # v2 (eng): the COLUMN-name heuristic misfires on railing / stair models that name horizontal rails COLUMN (Tekla IFC
        # of one such model: 54 of 68 COLUMN-named parts horizontal). Hold back only when the naming-independent checks do
        # not confirm the link (contour-plate names own their outlines; ANTIMATERIAL parts are cut-relation children).
        import attrlink
        db.find_cut_links(M)
        ev = attrlink.evidence(db, lay, M); st['attr_link_evidence'] = ev
        if not attrlink.confirmed(ev):
            st['status'] = 'suspect_attr_link'
            return st
        st['name_check']['overruled_by'] = 'attr_link_evidence'
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

    # code q: tekla-slots v2's 7.64 'PL a*b' thin-side rule (743 / 743 vs Tekla IFC) is the same rule as cut-not-applied P15 / P8 in
    # section_for (thickness = the smaller value, every engine): one copy, there; v2_rect stays as an (empty) statistic
    v2_rect = collections.Counter()

    def body(m):
        """-> (frame, profile_entity, depth, kind_label) or (None, reason)"""
        kind, v, how = section_for(m['prof'], cat)
        if m.get('cut') and P_CUTDEPTH.match((m.get('prof') or '').strip()):
            kind, v, how = None, 'contour_plate', None          # cut-not-applied P6: polygon cut part named by its bare depth
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
        if isinstance(prof, db1prof.Frustum): prof = db1prof.oriented(prof, m)  # db1prof-patch
        return (out.member_frame(m), prof, m['L'], how)

    # ---- v2: bolt groups of the record-discovered engines (7.5x-8.x): decode, place, holes (db1bolts2; interface of db1bolts)
    import db1bolts, db1bolts2
    BOLTS2 = os.environ.get('DB1_BOLTS', '1') == '1'
    bgroups = []; bstats = {}; bdec = None
    if BOLTS2:
        try:
            bdec = db1bolts2.BoltDecoder(db, pts, cs, lay)
            bgroups = bdec.decode(M)
        except Exception as ex_:
            import traceback
            bstats['decode_error'] = f'{type(ex_).__name__}: {str(ex_)[:200]} {traceback.format_exc()[-400:]}'; bgroups = []
    bseq = {g['seq']: g for g in bgroups}

    def is_bolt_record(m):
        """member records whose attribute record is a bolt group (obj_type 10) are not parts"""
        if m.get('seq') in bseq: return True
        if m.get('prof') and db1bolts.P_BOLTPROF.match(m['prof'].strip().upper()): return True
        if m.get('attr') is None: return False
        rr = db.lookup_all(m['attr'])
        return bool(rr) and int(db.I([rr[0] + 13])[0]) == 10
    REGION = {}
    _body0 = body

    def body(m):
        """the builder's body() + the part's section region (bolt-axis / ply intervals and holes)"""
        b_ = _body0(m)
        if BOLTS2 and b_[0] is not None:
            try:
                if b_[3] == 'contour_plate':
                    pts_ = [tuple(p.Coordinates) for p in b_[1].OuterCurve.Points]
                    if len(pts_) > 1 and pts_[0] == pts_[-1]: pts_ = pts_[:-1]
                    REGION[m['seq']] = (pts_, [])
                else:
                    kind_, v_, how_ = section_for(m['prof'], cat)
                    reg_ = db1bolts.outline(kind_, v_) if kind_ else None
                    if reg_ is not None: REGION[m['seq']] = reg_
            except Exception:
                pass
        return b_

    def std_fn(s_, d_, L_=None):   # c1audit-stdL
        """the model folder's own bolt catalog first, then Tekla's own dims (IFC harvest), then the standards tables"""
        cg_ = getattr(db1bolts, 'catalog_geometry', None)
        sg_ = cg_(s_, d_, L_) if cg_ else None
        return sg_ or db1bolts.fallback_geometry(s_, d_)   # c1audit-catalog: no name-keyed tables against the own assdb
    # cut-not-applied P12: Tekla fittings (relation type 9: planar end trims) and line cuts (type 12: plane cut, +normal side
    # removed) of the new engines, decoded by the eng fork's fittings.py (handed over to this stream; validated there against
    # Tekla IFC exports of 7.64 / 8.07 / 8.53 / 8.85 / 9.08 models). Perpendicular fittings on profile extrusions trim the member
    # (exact, no boolean), oblique ones / fittings on plates / line cuts are subtracted as half-space boxes. DB1_FITTINGS=0: off.
    FIT, LCUT, fit_info = {}, {}, {}
    fit_stats = collections.Counter(); FITP = {}; NOFIT = set()
    # code q (verifier 06:30Z): P12 is not regression-free outside its validation set (per-part volume vs Tekla IFC: 8.53 216 better /
    # 77 worse, 8.07 155 / 78; 1d8972fb W14X730 -88 %): off for the new engines by default (DB1_FITTINGS_NEW=1 turns it on); the
    # decoded fittings / line cuts are still counted and their parts tagged as not applied
    if os.environ.get('DB1_FITTINGS', '1') == '1':
        try:
            import fittings as _fit
            FIT, LCUT, fit_info = _fit.decode_all(db, cs, lay, M)
            apply_ = os.environ.get('DB1_FITTINGS_NEW', '0') == '1'
            _mf = re.search(r'(\d+\.\d+)', db.b[:16].decode('latin1'))
            _perp_on = (os.environ.get('DB1_FITTINGS_PERP', '1') == '1' and bool(_mf)
                        and _mf.group(1) in os.environ.get('DB1_FITTINGS_PERP_ENGINES', '8.07,8.53,8.85,9.08').split(','))
            fit_info = dict(fit_info, applied=apply_)
            for m in M:
                if m.get('cut') or (m['seq'] not in FIT and m['seq'] not in LCUT): continue
                if not apply_ and _perp_on and m['seq'] in FIT and m['seq'] not in LCUT and section_for(m['prof'], cat)[0] is not None:
                    _x = np.asarray(m['x'], float)
                    if all(abs(abs(float(np.asarray(n_, float) @ _x)) - 1) < 1e-6 for _, n_ in FIT[m['seq']]):
                        mm_, hs_, fn_ = _fit.plan(m, FIT[m['seq']], [], extrusion=True)
                        if not hs_ and not fn_.get('trim_skipped'):          # P12 perpendicular trims (Tekla IFC: 8.53 / 8.85 / 9.08 / 8.07 >= 98 %)
                            FITP[id(m)] = (mm_, []); fit_stats['perp_trims_applied'] += 1; fit_stats['trimmed'] += 'trim' in fn_; continue
                if not apply_:
                    NOFIT.add(id(m)); fit_stats['parts_not_applied'] += 1; continue
                mm_, hs_, fn_ = _fit.plan(m, FIT.get(m['seq'], []), LCUT.get(m['seq'], []), extrusion=section_for(m['prof'], cat)[0] is not None)
                FITP[id(m)] = (mm_, hs_); fit_stats['parts'] += 1; fit_stats['trimmed'] += 'trim' in fn_; fit_stats['halfspaces'] += len(hs_)
        except Exception as ex_:
            FITP = {}; NOFIT = set(); fit_info = dict(error=f'{type(ex_).__name__}: {str(ex_)[:200]}')
    cut_body = {}
    for m in M:
        if m.get('cut'):
            b = body(m)
            if b[0] is not None: cut_body[m['seq']] = b[:3]
            else: why['cut_body_zero_thickness' if zero_section(m.get('prof')) else 'cut_body_unbuilt'] += 1   # cut-not-applied P10
    applied = 0
    plist = []          # z3: one record per decoded part: [seq, profile, category, status, how/reason, GlobalId, n_cuts]
    # pass 1: bodies of the written parts (frame, depth, section region) for bolt placement and holes
    bodies = {}; isbolt = {}
    for m in M:
        if m.get('cut'): continue
        isbolt[id(m)] = BOLTS2 and is_bolt_record(m)
        if isbolt[id(m)]: continue
        bodies[id(m)] = body(FITP[id(m)][0] if id(m) in FITP else m)      # cut-not-applied P12: the fitted (trimmed) member
    BG = {}; HP = {}
    if BOLTS2 and bgroups:
        parts = {}; part_seqs = set()
        for m in M:
            b = bodies.get(id(m))
            if b and b[0] is not None:
                parts[m['seq']] = (b[0], b[2]); part_seqs.add(m['seq'])
        try:
            blinks = bdec.links(set(bseq), part_seqs)
            bstats['link_layout'] = getattr(bdec, 'link_layout', None)
            BG, HP, pst = db1bolts2.plan(bgroups, parts, REGION, blinks, std_fn, db1bolts.washer_t)
            bstats.update({str(k): v for k, v in pst.items()})
        except Exception as ex_:
            import traceback
            bstats['plan_error'] = f'{type(ex_).__name__}: {str(ex_)[:200]} {traceback.format_exc()[-400:]}'; BG, HP = {}, {}
    hole_prof = {}; holes_cut = 0; holes_round_for_slot = 0; holes_tol = 0
    # tekla-slots: which bolted parts Tekla slots (selection bits, bit k = k-th ply from the bolt head); Tekla NC 7.64: 1246 / 1249 parts (5 models), 8.53: 96 / 96 (2 models)
    _m2 = re.search(r'(\d+\.\d+)', db.b[:16].decode('latin1')); _eng2 = _m2.group(1) if _m2 else ''
    _bl2 = locals().get('blinks') or {}
    # code v: engines unchanged (7.64, 8.53). Tekla NC1 per-part selection on 193 archives (v decode, all engines forced on): 8.85 1706/1806
    # (94.5 %), 8.07 5943/6067 (98.0 %), 8.44 1970/2019, 7.82 5851/5988, 8.62 286/328, 9.08 283/283 (1 model) -> none reaches 99 % on a
    # multi-model sample; disagreements are whole groups slotted in the DB1 but round in the NC (stale NC or undecoded rule)
    V2_SLOTS_ON = BOLTS2 and os.environ.get('DB1_SLOTS', '1') == '1' and str(_eng2) in os.environ.get('DB1_V2_SLOT_ENGINES', '7.64,8.53').split(',')
    V2SLOT = {}; v2slot_why = collections.Counter(); v2_slot_holes = 0
    V2ROT = {}; v2_rotated = 0; V2_ROT_ON = os.environ.get('DB1_SLOT_ROTATE', '1') == '1'     # code v: Tekla 'rotate slots' (0 / 1 even / 2 odd plies)
    for g in (bgroups if BOLTS2 else []):
        sx_, sy_ = abs(g.get('slot_x') or 0), abs(g.get('slot_y') or 0)
        if not (sx_ or sy_): continue
        mk_ = g.get('slot_parts'); parts_ = _bl2.get(g['seq']) or []
        if not V2_SLOTS_ON:
            V2SLOT[g['seq']] = None if (mk_ is None or mk_) else {}; continue
        if mk_ is None or not parts_:
            V2SLOT[g['seq']] = None; v2slot_why['no_selection_or_part_list'] += 1; continue
        rot_ = (g.get('slot_rot') or 0) if V2_ROT_ON else 0
        if rot_ not in (0, 1, 2):                                   # code v: unknown 'rotate slots' value -> undecided (cut round, tagged)
            V2SLOT[g['seq']] = None; v2slot_why['rotate_slots_value_unknown'] += 1; continue
        n_ = len(parts_); full_ = (1 << min(n_, 5)) - 1
        if mk_ & full_ == 0:
            V2SLOT[g['seq']] = {p_: False for p_ in parts_}; v2slot_why['no_part_slotted'] += 1; continue
        if n_ <= 5 and mk_ & full_ == full_ and (rot_ == 0 or n_ == 1):
            V2SLOT[g['seq']] = {p_: True for p_ in parts_}; v2slot_why['every_part_slotted'] += 1
            if rot_ == 2: V2ROT[g['seq']] = {p_: True for p_ in parts_}     # code v: the single ply is ply 1 (odd)
            continue
        iv_ = {}
        for p_ in parts_:
            v_ = [(t0_, t1_) for (bb_, t0_, t1_) in HP.get(p_, []) if bb_.get('pid') == g['seq']]
            if v_: iv_[p_] = (sum(a for a, _ in v_) / len(v_), sum(c for _, c in v_) / len(v_))
        if len(iv_) < n_:
            V2SLOT[g['seq']] = None; v2slot_why['bolted_part_not_located_on_axis'] += 1; continue
        od_ = sorted(parts_, key=lambda p_: -(iv_[p_][0] + iv_[p_][1]))
        if any(iv_[od_[k + 1]][1] > iv_[od_[k]][0] + 1.0 for k in range(n_ - 1)):
            V2SLOT[g['seq']] = None; v2slot_why['overlapping_plies'] += 1; continue
        V2SLOT[g['seq']] = {p_: bool(k < 5 and (mk_ >> k) & 1) for k, p_ in enumerate(od_)}; v2slot_why['ranked_head_first'] += 1
        if rot_:                                                    # code v: k = 0 is ply 1 (odd)
            V2ROT[g['seq']] = {p_: (rot_ == 1 and k % 2 == 1) or (rot_ == 2 and k % 2 == 0) for k, p_ in enumerate(od_)}
    # pass 2: write
    for m in M:
        if m.get('cut'):
            why['cut_part_excluded'] += 1; continue
        if isbolt.get(id(m)):
            continue
        b = bodies.get(id(m)) or body(m)
        if b[0] is None:
            why[b[1]] += 1; unres[m['prof'] or '<none>'] += 1
            plist.append([m.get('seq'), m.get('prof'), part_cat(m.get('prof'), b[1]), 'skipped', b[1], None, 0]); continue
        cuts = [cut_body[c] for c in links.get(m['seq'], []) if c in cut_body] if PART_CUTS_ON else []
        applied += len(cuts)
        if PART_CUTS_ON and FITP.get(id(m), (None, None))[1]:          # cut-not-applied P12: oblique fittings / line cuts
            size_ = 2.0 * (FITP[id(m)][0]['L'] + 2000.0)
            cuts = cuts + [_fit.halfspace_cut(out, P_, n_, size_) for P_, n_ in FITP[id(m)][1]]
            fit_stats['halfspaces_applied'] += len(FITP[id(m)][1])
        nh = 0
        for bb, z0, z1 in HP.get(m['seq'], []):
            dh, dec_ = db1bolts.hole_diameter(bb)
            holes_tol += 1 if dec_ else 0
            key = round(dh, 2)
            ss_ = V2SLOT.get(bb.get('pid'))
            if ss_ and ss_.get(m['seq']):                        # tekla-slots: slotted hole, long side along the group x / y
                g_ = bseq.get(bb.get('pid')) or {}; sx_, sy_ = abs(g_.get('slot_x') or 0), abs(g_.get('slot_y') or 0)
                if (V2ROT.get(bb.get('pid')) or {}).get(m['seq']):      # code v: Tekla 'rotate slots' in this ply
                    sx_, sy_ = sy_, sx_; v2_rotated += 1
                key = ('S', round(dh, 3), round(sx_, 3), round(sy_, 3)); v2_slot_holes += 1
                if key not in hole_prof:
                    hole_prof[key] = out.profile('BOLT_SLOT_D%g_X%g_Y%g' % key[1:], 'RRECT', [dh + sx_, dh + sy_, dh / 2])
            elif key not in hole_prof:
                hole_prof[key] = out.profile('BOLT_HOLE_D%g' % key, 'CIRC', [dh / 2])
            p0 = bb['p0']
            cuts = cuts + [((p0 + bb['ez'] * (z0 - 2.0), bb['ez'], bb['ex']), hole_prof[key], (z1 - z0) + 4.0)]
            nh += 1
        holes_cut += nh
        cat_ = part_cat(m.get('prof'), b[3])
        cls = 'IfcPlate' if cat_ in ('connection', 'other') and b[3] not in ('parametric_stud_shank', 'parametric_anchor') else (
              'IfcMechanicalFastener' if b[3] in ('parametric_stud_shank', 'parametric_anchor') else 'IfcBeam')
        nm_n = approx_name(m['prof'], b[3])
        if id(m) in NOFIT:
            nm_n += ' [approx: Tekla fitting / line cut not applied (new-engine fittings not validated)]'
        rp_ = [getattr(db, 'repaired', {})[c] for c in links.get(m['seq'], []) if c in cut_body and c in getattr(db, 'repaired', {})] if PART_CUTS_ON else []
        if rp_:                                                        # cut-not-applied P14
            nm_n += ' [approx: cut outline self-crossing slivers dropped (%.2f of %.0f mm2)]' % max(rp_); fit_stats['parts_with_repaired_cut_outline'] += 1
        e = out.element(cls, nm_n, b[0], b[1], b[2], cuts)
        plist.append([m.get('seq'), m.get('prof'), cat_, 'written', b[3], e.GlobalId, len(cuts)])
        src[b[3]] += 1
    # bolt groups: decoded ones written (or holes only); undecoded bolt records listed as skipped bolt groups
    for g in bgroups:
        bl_all = BG.get(g['seq']) or []
        bl = [bb for bb in bl_all if not bb.get('holes_only')]
        nm0 = g.get('prof') or f"BOLT {g['d']:g}x{g['L']:g}"
        if bl_all and not bl:
            plist.append([g['seq'], nm0, 'feature', 'written', 'holes_only_group', None, 0]); src['holes_only_group'] += 1
            continue
        if not bl:
            plist.append([g['seq'], nm0, 'connection', 'skipped', 'bolt_group_unplaced', None, 0]); why['bolt_group_unplaced'] += 1
            continue
        sg = bl[0].get('std'); tags = []
        if not sg: tags.append('head and nut nominal (1.6d across flats, 0.65d / 0.8d): no table for this standard/diameter')
        if any(bb.get('tol') is None for bb in bl): tags.append('hole = d + standard clearance (tolerance not decoded)')
        if any(bb.get('head_up') and not bb.get('axial_decoded') for bb in bl): tags.append('axial position from the connected plies (record grip centre differs)')
        if any(not bb.get('head_up') for bb in bl): tags.append('axial position unknown (no connected ply on the axis): shank centred on the bolt plane')
        if any(bb.get('wash_head') or bb.get('wash_nut') or bb.get('wash_2') for bb in bl) and not all(db1bolts.washer_exact(bb) for bb in bl):   # c1audit-stats
            tags.append('washer thickness nominal')
        if g['seq'] in V2SLOT and V2SLOT[g['seq']] is None:      # tekla-slots: only undecoded / unranked slotted groups stay round
            tags.append('slotted holes cut as round holes (slotted parts not verified)'); holes_round_for_slot += 1
        nm = f"{nm0} {g.get('standard') or ''}" + (f" ({sg['family']}, {sg.get('mapping', '')})" if sg else '')
        e = out.bolt_group(_c1_name(nm, tags), bl)   # c1audit-stats
        plist.append([g['seq'], nm0, 'connection', 'written', 'bolt_group', e.GlobalId, 0]); src['bolt_group'] += 1
    for m in M:
        if isbolt.get(id(m)) and m['seq'] not in bseq:
            plist.append([m.get('seq'), m.get('prof'), 'connection', 'skipped', 'bolt_group_excluded', None, 0]); why['bolt_group_excluded'] += 1
    if BOLTS2 and os.environ.get('DB1_BOLT_DEBUG'):
        st['bolt_debug'] = {str(g['seq']): [[round(float(u), 3), round(float(v), 3), (round(float(bb['zh']), 3) if bb.get('zh') is not None else None),
                                              [round(float(x), 3) for x in bb['grip']] if bb.get('grip') else None, bb.get('axial')]
                                             for (u, v), bb in zip(g['uv'], BG.get(g['seq']) or [])] for g in bgroups}
    if BOLTS2:
        _all = [bb for g in bgroups for bb in (BG.get(g['seq']) or [])]
        _real = [bb for bb in _all if not bb.get('holes_only')]
        _wn = 0
        for bb in _real:
            _w = (bb.get('wash_head') or 0) + (bb.get('wash_nut') or 0) + (bb.get('wash_2') or 0)
            if _w and not db1bolts.washer_exact(bb) and not ((bb.get('std') or {}).get('washer_t')): _wn += _w
        st['bolt_stats'] = dict(bstats, groups_decoded=len(bgroups), groups_written=src.get('bolt_group', 0),
                                holes_only_groups=src.get('holes_only_group', 0), holes_cut=holes_cut, holes_tolerance_decoded=holes_tol,
                                # keys read by the grader (build_index.classify_db1), same meaning as the old-engine writer's
                                bolts=len(_all), standard_table_geometry=sum(1 for bb in _all if bb.get('std')),
                                holes_nominal_clearance=holes_cut - holes_tol,
                                washers=sum((bb.get('wash_head') or 0) + (bb.get('wash_nut') or 0) + (bb.get('wash_2') or 0) for bb in _real),
                                washers_nominal=_wn,
                                washer_side_inferred=sum(1 for bb in _real if (bb.get('wash_2') or 0) > 0),
                                bolts_shifted_to_plies=sum(1 for bb in _real if bb.get('head_up') and not bb.get('axial_decoded')),
                                bolts_without_holed_part=sum(1 for bb in _all if not bb.get('grip')),
                                slotted_groups_cut_round=holes_round_for_slot,
                                decoder={str(k): v for k, v in (bdec.stats.items() if bdec else [])},
                                standards=dict(collections.Counter(g.get('standard') or '?' for g in bgroups)),
                                geometry_sources=dict(collections.Counter(((BG.get(g['seq']) or [{}])[0].get('std') or {}).get('source') or 'nominal' for g in bgroups if BG.get(g['seq']))),
                                hole_diameter='stored bolt d + decoded tolerance (8.x group attribute / bolt string field 3)',
                                writer='db1bolts2 v2 (7.5x-9.x records) + db1bolts.bolt_group')
        st['bolt_stats'].update(_c1_v2_stats(bgroups, BG, holes_cut, holes_tol, db1bolts))   # c1audit-stats
        st['bolt_stats']['slotted_bolts_cut_round'] = sum(len(BG.get(s_) or []) for s_, v_ in V2SLOT.items() if v_ is None)   # tekla-slots
        st['bolt_stats'].update(slotted_holes_cut=v2_slot_holes, slot_groups=dict(v2slot_why), v2_slots_on=V2_SLOTS_ON, slots_rotated=v2_rotated,
                                rect_plates_thin_side_to_z=sum(v2_rect.values()), rect_plate_names_reordered=dict(v2_rect.most_common(10)))
    st['parts_list'] = plist
    st['cuts_applied'] = applied
    # cut-not-applied P11: every cut part accounted for (the grade flag cuts_not_applied only sees unbuilt bodies)
    _wr = {p[0] for p in plist if p[3] == 'written'}; _lk = {c for v in links.values() for c in v}
    st['cut_stats'] = dict(cut_parts=sum(1 for m in M if m.get('cut')), bodies_built=len(cut_body), applied=applied,
                           unlinked=sum(1 for m in M if m.get('cut') and m['seq'] not in _lk),
                           links_to_unwritten_parts=sum(1 for p, cs in links.items() if p not in _wr for c in cs if c in cut_body))
    st['fittings'] = dict(fit_info, **fit_stats)                      # cut-not-applied P12
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


POLY_TAG = ' [approx: polybeam - straight segments along the stored polyline, mitred corners (bend chamfers not decoded)]'   # audit P5


def _perp(v):
    v = np.asarray(v, float); a = np.array([1.0, 0, 0]) if abs(v[0]) < 0.9 else np.array([0, 1.0, 0])
    a = a - (a @ v) * v; return a / np.linalg.norm(a)


def polybeam_segments(m, outline):
    """audit P5: old-engine polybeam (form 4, >= 3 points = world offsets from O; the record length L is the first segment)
    -> ([{frame, depth, clips, hit_frame, hit_depth}], capped corners) | reason string"""
    P = [np.asarray(p, float) for p in (m.get('old_poly') or [])]
    Q = [P[0]] if P else []
    for p in P[1:]:
        if np.linalg.norm(p - Q[-1]) > 1e-6: Q.append(p)
    if len(Q) < 3: return 'lt3_points'
    O = np.asarray(m['O'], float); Wp = [O + q for q in Q]
    D = [Wp[k + 1] - Wp[k] for k in range(len(Wp) - 1)]; Ls = [float(np.linalg.norm(x)) for x in D]; D = [x / l for x, l in zip(D, Ls)]
    if abs(float(D[0] @ np.asarray(m['x'], float))) < 0.999 or abs(Ls[0] - m['L']) > 0.6: return 'frame_mismatch'
    if not outline or not outline[0]: return 'no_outline'
    R = max(math.hypot(a, b) for a, b in outline[0])
    y = np.asarray(m['y'], float); y = y - (y @ D[0]) * D[0]; y = y / np.linalg.norm(y); ys = [y]
    for k in range(1, len(D)):
        a = np.cross(D[k - 1], D[k]); s = float(np.linalg.norm(a)); c = float(D[k - 1] @ D[k]); yk = ys[-1]
        if s > 1e-9:
            a = a / s; th = math.atan2(s, c)
            yk = yk * math.cos(th) + np.cross(a, yk) * math.sin(th) + a * (a @ yk) * (1 - math.cos(th))
        yk = yk - (yk @ D[k]) * D[k]; ys.append(yk / np.linalg.norm(yk))
    sgn = m['sgn']; segs = []; capped = 0
    for k in range(len(D)):
        es = ee = 0.0; clips = []
        for j, end in ((k, 'start'), (k + 1, 'end')):
            if (end == 'start' and k == 0) or (end == 'end' and k == len(D) - 1): continue
            d0, d1 = D[j - 1], D[j]
            th = math.acos(float(np.clip(d0 @ d1, -1, 1)))
            if th > math.radians(150): capped += 1
            e = min(R * math.tan(min(th, math.radians(150)) / 2), 5 * R) + 1.0
            n = d0 + d1; n = n / np.linalg.norm(n) if np.linalg.norm(n) > 1e-9 else d0
            if end == 'start': es = e; clips.append((Wp[j], n, True))
            else: ee = e; clips.append((Wp[j], n, False))
        A = Wp[k] - D[k] * es; B = Wp[k + 1] + D[k] * ee; xr_k = sgn * D[k]; X = np.cross(xr_k, ys[k])
        segs.append({'frame': (B if sgn == 1 else A, -xr_k, X), 'depth': Ls[k] + es + ee, 'clips': clips,
                     'hit_frame': (Wp[k + 1] if sgn == 1 else Wp[k], -xr_k, X), 'hit_depth': Ls[k]})
    return segs, capped


def convert_old(data, out_ifc, cat, engine, t0):
    import db1old
    M, info, cut_rel = db1old.read(data, engine)
    _null = [m for m in M if db1prof.is_null_record(m)]  # db1prof-patch
    M = [m for m in M if not db1prof.is_null_record(m)]
    bad_axis = sum(1 for m in M if m.get('axis_ok') is False)
    M = [m for m in M if m.get('axis_ok') is not False]
    st = dict(layout={'engine': engine, 'format': 'old', **info}, decode_sec=round(time.time() - t0, 1), mb=round(len(data) / 1e6, 2), members=len(M),
              axis_mismatch_dropped=bad_axis, null_records=len(_null), null_record_names=sorted({m.get('prof') or '' for m in _null})[:10])
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
        if m.get('cut') and P_CUTDEPTH.match((m.get('prof') or '').strip()):
            kind, v, how = None, 'contour_plate', None          # cut-not-applied P6: polygon cut part named by its bare depth
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
        # code p: the tekla-slots swap (plate thickness = the smaller value, along z) now lives in section_for (cut-not-applied
        # P15 'PL a*b' / P8 'F.B AxB', both engines); only its statistics stay here (names whose first value is the larger one)
        if kind == 'RECT' and how in ('parametric', 'parametric_flat_bar') and RECT_THIN_Z and m.get('pid') not in RECT_PIDS:
            nums_ = re.findall(r'\d+(?:\.\d+)?', m['prof'] or '')
            if len(nums_) >= 2 and float(nums_[0]) > float(nums_[1]): RECT_PIDS.add(m.get('pid')); rect_thin_z[m.get('prof')] += 1
        prof = out.profile(m['prof'], kind, v)
        if isinstance(prof, db1prof.Frustum): prof = db1prof.oriented(prof, m)  # db1prof-patch
        if prof is not None and BOLTS_ON:
            REGION[id(m)] = db1bolts.outline(kind, v)
        if (ARCS_ON and prof is not None and not m.get('cut') and not isinstance(prof, db1prof.Frustum) and m.get('form') == 4
                and len(m.get('old_poly') or []) == 3 and list((m.get('old_poly_ch') or [])[:3]) == [0, 40, 0] and id(m) not in ARC):
            a_ = _arc3(m)                                                    # arc patch: Tekla curved beam (arc point)
            if a_ is not None:
                ARC[id(m)] = a_; POLY_SEEN.add(id(m)); arc_stats['curved_beams'] += 1
            else:
                arc_stats['arc_point_not_resolved'] += 1
        if (POLYBEAM and prof is not None and not m.get('cut') and not isinstance(prof, db1prof.Frustum) and m.get('form') == 4
                and len(m.get('old_poly') or []) >= 3 and id(m) not in POLY_SEEN):          # audit P5
            POLY_SEEN.add(id(m)); r_ = polybeam_segments(m, db1bolts.outline(kind, v))
            if isinstance(r_, tuple):
                POLY[id(m)] = r_[0]; poly_stats['polybeams'] += 1; poly_stats['segments'] += len(r_[0]); poly_stats['corners_over_150deg'] += r_[1]
            else:
                poly_stats['polybeam_kept_straight_' + r_] += 1
        return (out.member_frame(m), prof, m['L'], how) if prof is not None else (None, 'writer_skip')

    REGION = {}
    RECT_THIN_Z = os.environ.get('DB1_RECT_THIN_Z', '1') == '1'; RECT_PIDS = set(); rect_thin_z = collections.Counter()   # tekla-slots
    POLYBEAM = os.environ.get('DB1_POLYBEAM', '1') == '1'; POLY = {}; POLY_SEEN = set(); poly_stats = collections.Counter()   # audit P5
    ARCS_ON = os.environ.get('DB1_ARCS', '1') == '1'; ARC = {}; arc_stats = collections.Counter()                                 # arc patch
    # tag kept until the volume residual is explained (6eab vs Tekla 16.1: bbox 7 / 7 <= 1 mm; volume vs the straight-member baseline of
    # the same profile W14X30 +0.1 % (3), W14X48 +1.6 % (4))
    ARC_TAG = ' [approx: curved beam = circular arc through the 3 stored points (Tekla arc point); bbox validated, volume +0..1.6 % vs Tekla]'

    def _arc3(m):
        """circle through the 3 stored points (world = O + offset) -> frame at P0 (Z = tangent, Y = part y), axis + angle in that frame"""
        P = [np.asarray(m['O'], float) + np.asarray(q, float) for q in m['old_poly']]
        a, b, c = P; ab, bc = b - a, c - b; n = np.cross(ab, bc); nn = np.linalg.norm(n)
        if nn < 1e-6 * np.linalg.norm(ab) * np.linalg.norm(bc): return None
        n = n / nn
        # circumcentre in the plane
        A = np.array([ab, bc, n]); rhs = np.array([ab @ (a + b) / 2, bc @ (b + c) / 2, n @ a])
        C = np.linalg.solve(A, rhs); R = float(np.linalg.norm(a - C))
        ra, rc = (a - C) / R, (c - C) / R
        t0 = np.cross(n, ra)                                                  # tangent at P0, turning towards b and c (n = ab x bc)
        th = float(np.arctan2(np.cross(ra, rc) @ n, ra @ rc)) % (2 * np.pi)
        if th < 1e-6: return None
        y = np.asarray(m['y'], float); y = y - (y @ t0) * t0
        if np.linalg.norm(y) < 1e-6: return None
        y = y / np.linalg.norm(y); X = np.cross(-t0, y)                       # profile x / y as in member_frame (Y = part y)
        fr = (a, t0, X); Rm = np.stack([X, np.cross(t0, X), t0], 1)
        return dict(frame=fr, loc=Rm.T @ (C - a), dir=Rm.T @ n, angle=th, R=R, C=C, n=n)
    HOLE_DEDUP = os.environ.get('DB1_HOLE_DEDUP', '1') == '1'; holes_merged = [0]; near_merged = [0]; p6_apart = [0]          # audit P6
    import db1bolts
    eng_s = '%.2f' % engine
    BOLTS_ON = os.environ.get('DB1_BOLTS', '1') == '1' and eng_s in db1bolts.BOLT_ENGINES
    BL = []
    if BOLTS_ON:
        for m in M:
            if m.get('bolt') and not m.get('cut'):
                for b in db1bolts.bolts_of(m):
                    b.setdefault('_prof', m.get('prof'))      # c1audit-stats
                    BL.append(b)
    HI = db1bolts.HoleIndex(BL)
    hole_prof = {}
    holes_cut = 0; ax_stats = {}; holes_tol_decoded = 0
    hole_src = collections.Counter(); holes_no_hole = 0; holes_slot_round = 0   # hole-tolerance-residue: diameter source per hole
    holes_inside = 0; inside_prof = collections.Counter(); inside_why = collections.Counter()

    # cut-not-applied P13: Tekla fittings (type 9) / line cuts (type 12) decoded by db1old.read (db1old.FIT). DB1_FITTINGS=0: off.
    FITP = {}; fit_stats = collections.Counter(); _FIT = getattr(db1old, 'FIT', {}) if os.environ.get('DB1_FITTINGS', '1') == '1' else {}
    if _FIT:
        import fittings as _fit
        for m in M:
            if m.get('cut') or m.get('bolt'): continue
            fl_ = _FIT.get(9, {}).get(m['pid'], []); lc_ = _FIT.get(12, {}).get(m['pid'], [])
            if not fl_ and not lc_: continue
            k_, v_, _h = section_for(m['prof'], cat)
            mm_, hs_, nt_ = fit_old_plan(m, fl_, lc_, k_, v_)
            FITP[id(m)] = (mm_, hs_); fit_stats['parts'] += 1; fit_stats['moved_ends'] += mm_ is not m; fit_stats['halfspaces'] += len(hs_)
            fit_stats.update(nt_)
    cut_body = {}
    for m in M:
        if m.get('cut'):
            b = body(m)
            if b[0] is not None: cut_body[m['pid']] = b[:3]
            else: why['cut_body_zero_thickness' if zero_section(m.get('prof')) else 'cut_body_unbuilt'] += 1   # cut-not-applied P10
    applied = 0
    plist = []
    # pass 1: bodies of every written part (cached) and, with bolts on, which parts each bolt passes through + the plies' extent
    bodies = {}
    for m in M:
        if m.get('cut') or (BOLTS_ON and m.get('bolt') and db1bolts.bolts_of(m)):
            continue
        if FITP.get(id(m), (m,))[0] is not m:                          # cut-not-applied P13: the fitted member; body() keys the section
            mm_ = FITP[id(m)][0]; bodies[id(m)] = body(mm_)              # region (bolt holes) and polybeam segments by id(member)
            if id(mm_) in REGION: REGION[id(m)] = REGION.pop(id(mm_))
            if id(mm_) in POLY: POLY[id(m)] = POLY.pop(id(mm_))
        else:
            bodies[id(m)] = body(m)
    part_bolts = {}; spans = [[] for _ in BL]
    HOLE_REL = os.environ.get('DB1_HOLE_REL', '1') == '1'; dropped_holes = [0]        # audit P4
    REL10 = collections.defaultdict(set)
    for a_, b_ in getattr(db1old, 'REL', {}).get(10, []):
        REL10[a_].add(b_); REL10[b_].add(a_)
    REL10L = collections.defaultdict(list)                   # tekla-slots: bolt group -> its bolted parts
    for a_, b_ in getattr(db1old, 'REL', {}).get(10, []):
        if b_ not in REL10L[a_]: REL10L[a_].append(b_)
    PLY = {}                                                 # tekla-slots: (bolt index, part pid) -> ply span along the bolt axis
    # engines whose slot direction is validated vs Tekla NC (6.87 = the 7.01 record layout; 7.24: parts 116 / 116 but 8 / 92 slots
    # rotated 90 deg vs NC -> off until Tekla's 'rotate slots' field is found)
    # code v: engines unchanged (6.87, 7.01). Tekla NC1 per part (v decode forced on, same-revision NC): 7.24 2370/2496 (95 %, 8 models; the
    # misses are whole groups the DB1 marks slotted that Tekla's NC drills round - no stored field separates them), 7.30 546/546 (1 model)
    SLOTS_ON = os.environ.get('DB1_SLOTS', '1') == '1' and eng_s in os.environ.get('DB1_SLOT_ENGINES', '6.87,7.01').split(',')
    SLOT_SET = {}; slot_why = collections.Counter(); slot_holes = [0]
    # code v: Tekla 'rotate slots' (part-attr byte @368: 0 no, 1 even plies, 2 odd plies, ply 1 = first from the bolt head) turns the slot
    # 90 deg in those plies; NC1 truth: every rotated slot of 6.87 / 7.24 / 7.30 had this byte set, every unrotated one 0
    SLOT_ROT_ON = os.environ.get('DB1_SLOT_ROTATE', '1') == '1'; ROTP = {}; slots_rotated = [0]
    inside = {}      # (part, bolt) -> why the bolt is not a ply of the part (no hole cut there): it runs along / inside the part
    if BOLTS_ON and BL:
        # code q (verifier 06:30Z on audit P4): pass A collects every part a bolt meets; a group whose type-10 bolted list names none
        # of the parts the bolt actually meets falls back to the geometric grip rule (before: 990 real and 1,158 holes-only bolts lost
        # every hole); a part in the group's list always keeps its hole (also over the not-a-ply rule below: 8 genuine holes)
        CAND = []
        for m in M:
            b = bodies.get(id(m))
            if not b or b[0] is None:
                continue
            reg = REGION.get(id(m))
            if reg is None:
                continue
            if id(m) in ARC:                                                  # arc patch: holes of the bolts whose group lists this part
                part_bolts[id(m)] = [i for i, bb_ in enumerate(BL) if m.get('pid') in (REL10.get(bb_.get('pid')) or ())]
                for i in part_bolts[id(m)]: HI.hits[i] += 1
                continue
            segs_ = POLY.get(id(m)) or [{'hit_frame': b[0], 'hit_depth': b[2]}]          # audit P5: every polybeam segment
            hf_ = {}
            for sg_ in segs_:
                for i in HI.holes_for(sg_['hit_frame'], sg_['hit_depth'], reg):
                    if i in hf_: HI.hits[i] -= 1
                    else: hf_[i] = (sg_['hit_frame'], sg_['hit_depth'])
            CAND.append((m, b, reg, hf_))
        LISTED_HIT = set()                                       # bolts that meet at least one part of their group's bolted list
        for m, b, reg, hf_ in CAND:
            for i in hf_:
                g_ = REL10.get(BL[i].get('pid'))
                if g_ and m.get('pid') in g_: LISTED_HIT.add(i)
        p4_fallback = [0]
        for m, b, reg, hf_ in CAND:
            hit = list(hf_)
            if hit and HOLE_REL:                                   # audit P4: holes only in Tekla's bolted parts, within the grip
                keep = []
                for i in hit:
                    bb_ = BL[i]; g_ = REL10.get(bb_.get('pid'))
                    if g_ and i not in LISTED_HIT:
                        g_ = None; p4_fallback[0] += 1                # the list names none of the parts this bolt meets: geometric rule
                    ok_ = m.get('pid') in g_ if g_ else True          # Tekla's bolted-part list is authoritative when the group has one
                    if ok_ and not g_ and bb_.get('axial_decoded') and bb_.get('grip'):   # no list: the part must meet the decoded grip
                        sp_ = db1bolts.ply_check(hf_[i][0], hf_[i][1], reg, bb_)
                        off_ = bb_['zh'] - bb_['L'] / 2
                        ok_ = sp_ is not None and sp_[1] >= bb_['grip'][0] - off_ - 1.0 and sp_[0] <= bb_['grip'][1] - off_ + 1.0
                    if ok_: keep.append(i)
                    else: HI.hits[i] -= 1; dropped_holes[0] += 1
                hit = keep
            if hit:
                part_bolts[id(m)] = hit
                for i in hit:
                    zp_ = np.asarray(hf_[i][0][1], float); zp_ = zp_ / (np.linalg.norm(zp_) or 1.0)    # axis of the (segment) frame
                    sp = db1bolts.ply_check(hf_[i][0], hf_[i][1], reg, BL[i])
                    if sp:
                        spans[i].append(sp); PLY[(i, m.get('pid'))] = sp
                        # not a ply (no hole cut there): material over the whole shank +- 2d (bolt embedded in / running inside a member), or a
                        # member parallel to the bolt whose material reaches past an end of that window (rod / bar / beam threaded through the
                        # hole); contour plates bolted through their thickness and thin parts along the axis (modelled washers / nuts) are cut
                        w_ = BL[i]['L'] / 2 + 2 * BL[i]['d'] - 1.0
                        lo_, hi_ = sp[0] <= -w_, sp[1] >= w_
                        par_ = abs(float(zp_ @ BL[i]['ez'])) > 0.996
                        if b[3] == 'contour_plate' and par_:
                            pass                                     # bolted through the plate thickness: a ply, whatever its thickness
                        elif lo_ and hi_:
                            inside[(id(m), i)] = 'inside_window'
                        elif (lo_ or hi_) and b[3] != 'contour_plate' and par_:
                            inside[(id(m), i)] = 'along_member_axis'
                        g10_ = REL10.get(BL[i].get('pid'))
                        if (id(m), i) in inside and g10_ and m.get('pid') in g10_:
                            inside.pop((id(m), i), None)             # code q: a part in the group's bolted list keeps its hole
                        if (id(m), i) in inside: PLY.pop((i, m.get('pid')), None)      # tekla-slots: not a ply
        # tekla-slots: which bolted parts Tekla slots. The selection bits (attribute int @16, bit k = part k+1) number the group's
        # bolted parts by their ply along the bolt from the head (+z) side (Tekla NC: 7.01 374 / 374, 7.24 116 / 116 parts)
        if SLOTS_ON:
            gb_ = collections.defaultdict(list)
            for i, bb in enumerate(BL): gb_[bb.get('pid')].append(i)
            for g_, idx_ in gb_.items():
                b0_ = BL[idx_[0]]
                if not any(abs(float(x)) > 1e-9 for x in (b0_.get('slot') or (0.0, 0.0))): continue
                parts_ = REL10L.get(g_) or []; n_ = len(parts_); mk_ = int(b0_.get('slot_mask') or 0)
                rot_ = (b0_.get('slot_rot') or 0) if SLOT_ROT_ON else 0
                if b0_.get('slot_mask') is None or not n_:
                    SLOT_SET[g_] = None; slot_why['no_selection_or_part_list'] += 1; continue
                if rot_ not in (0, 1, 2):                          # code v: unknown 'rotate slots' value -> undecided (cut round, tagged)
                    SLOT_SET[g_] = None; slot_why['rotate_slots_value_unknown'] += 1; continue
                full_ = (1 << min(n_, 5)) - 1
                if mk_ & full_ == 0:
                    SLOT_SET[g_] = {p_: False for p_ in parts_}; slot_why['no_part_slotted'] += 1; continue
                if n_ <= 5 and mk_ & full_ == full_ and (rot_ == 0 or n_ == 1):
                    SLOT_SET[g_] = {p_: True for p_ in parts_}; slot_why['every_part_slotted'] += 1
                    if rot_ == 2: ROTP[g_] = {p_: True for p_ in parts_}      # code v: the single ply is ply 1 (odd)
                    continue
                win_ = []                                          # the recorded grip window of each bolt (old-engine bolt string)
                for i in idx_:
                    bb = BL[i]
                    if bb.get('grip') and bb.get('zh') is not None:
                        off_ = bb['zh'] - bb['L'] / 2; win_.append((bb['grip'][0] - off_, bb['grip'][1] - off_))
                wl_ = sum(b_ - a_ for a_, b_ in win_) / len(win_) if win_ else None
                iv_ = {}; wide_ = set()
                for p_ in parts_:
                    v_ = []
                    for i in idx_:
                        sp_ = PLY.get((i, p_))
                        if sp_ is None: continue
                        bb = BL[i]; lo_, hi_ = sp_
                        if bb.get('grip') and bb.get('zh') is not None:      # plies of the recorded grip (window +- 0.5 mm)
                            off_ = bb['zh'] - bb['L'] / 2; lo2_ = max(lo_, bb['grip'][0] - off_ - 0.5); hi2_ = min(hi_, bb['grip'][1] - off_ + 0.5)
                            if hi2_ > lo2_: lo_, hi_ = lo2_, hi2_
                        v_.append((lo_, hi_))
                    if v_:
                        iv_[p_] = (sum(a for a, _ in v_) / len(v_), sum(c for _, c in v_) / len(v_))
                        if wl_ is not None and iv_[p_][1] - iv_[p_][0] >= wl_ + 0.5: wide_.add(p_)   # fills the whole grip: not a ply
                loc_ = [p_ for p_ in parts_ if p_ in iv_ and p_ not in wide_]; miss_ = [p_ for p_ in parts_ if p_ not in loc_]
                how_ = 'ranked_head_first'
                if miss_:
                    # one bolted part not located as a ply: the recorded grip window is filled by the plies, so it lies in the gap the located
                    # plies leave at one end of the window (Tekla NC 7.01: 250 / 252 parts)
                    if len(miss_) != 1 or not loc_ or not win_:
                        SLOT_SET[g_] = None; slot_why['bolted_part_not_located_on_axis'] += 1; continue
                    glo_ = sum(a_ for a_, _ in win_) / len(win_); ghi_ = sum(b_ for _, b_ in win_) / len(win_)
                    top_ = max(iv_[p_][1] for p_ in loc_); bot_ = min(iv_[p_][0] for p_ in loc_)
                    # plies are sampled every 0.5 mm (ply_check): flush = within 1.5 mm, the gap of the missing ply >= 3 mm (7.01: 250 / 252)
                    if ghi_ - top_ >= 3.0 and abs(bot_ - glo_) <= 2.0 and (ghi_ - top_) - abs(bot_ - glo_) >= 3.0: iv_[miss_[0]] = (top_, ghi_)
                    elif bot_ - glo_ >= 3.0 and abs(ghi_ - top_) <= 2.0 and (bot_ - glo_) - abs(ghi_ - top_) >= 3.0: iv_[miss_[0]] = (glo_, bot_)
                    else:
                        SLOT_SET[g_] = None; slot_why['bolted_part_not_located_on_axis'] += 1; continue
                    how_ = 'ranked_head_first_grip_window'
                od_ = sorted(parts_, key=lambda p_: -(iv_[p_][0] + iv_[p_][1]))
                if any(iv_[od_[k + 1]][1] > iv_[od_[k]][0] + 1.0 for k in range(n_ - 1)):     # 2 x the 0.5 mm ply sampling
                    # tekla-slots A: 2 parts, exactly one ply flush with an end of the recorded grip window and a >= 3 mm gap at the other
                    # end -> the other part fills that gap (Tekla NC 7.01: 14 / 14 parts)
                    fl_ = None
                    if n_ == 2 and win_ and how_ == 'ranked_head_first':
                        glo_ = sum(a_ for a_, _ in win_) / len(win_); ghi_ = sum(b_ for _, b_ in win_) / len(win_)
                        ft_ = [p_ for p_ in parts_ if abs(iv_[p_][1] - ghi_) <= 2.0]; fb_ = [p_ for p_ in parts_ if abs(iv_[p_][0] - glo_) <= 2.0]
                        if len(ft_) == 1 and not fb_ and iv_[ft_[0]][0] - glo_ >= 3.0:
                            fl_ = [ft_[0]] + [p_ for p_ in parts_ if p_ != ft_[0]]
                        elif len(fb_) == 1 and not ft_ and ghi_ - iv_[fb_[0]][1] >= 3.0:
                            fl_ = [p_ for p_ in parts_ if p_ != fb_[0]] + [fb_[0]]
                    if fl_ is None:
                        SLOT_SET[g_] = None; slot_why['overlapping_plies'] += 1; continue
                    od_ = fl_; how_ = 'ranked_head_first_grip_window_flush_ply'
                SLOT_SET[g_] = {p_: bool(k < 5 and (mk_ >> k) & 1) for k, p_ in enumerate(od_)}; slot_why[how_] += 1
                if rot_:                                           # code v: k = 0 is ply 1 (odd)
                    ROTP[g_] = {p_: (rot_ == 1 and k % 2 == 1) or (rot_ == 2 and k % 2 == 0) for k, p_ in enumerate(od_)}
            for bb in BL:
                if bb.get('pid') in SLOT_SET:
                    bb['slot_state'] = 'unresolved' if SLOT_SET[bb.get('pid')] is None else 'decoded'
        # axial fit: shift each bolt along its axis so that its shank covers the plies it passes through (head on -z, as written by
        # the Windows pipeline); bolts shorter than their grip are centred on the grip and counted
        shifted = 0; short = 0; inside0 = 0
        for i, bb in enumerate(BL):
            if not spans[i] or bb.get('axial_decoded') or bb.get('holes_only'):
                continue
            a_ = min(x[0] for x in spans[i]); b_ = max(x[1] for x in spans[i]); L = bb['L']
            if a_ >= -L / 2 - 0.5 and b_ <= L / 2 + 0.5:
                inside0 += 1; continue
            if b_ - a_ <= L:
                sh = (a_ + L / 2) if a_ < -L / 2 else (b_ - L / 2)
            else:
                sh = (a_ + b_) / 2; short += 1
            bb['c'] = bb['c'] + bb['ez'] * sh; bb['shift'] = sh; shifted += 1
        ax_stats = {'bolts_with_plies': sum(1 for x in spans if x), 'plies_inside_centred_shank': inside0, 'bolts_shifted_to_plies': shifted,
                    'bolts_shorter_than_grip': short}
    # pass 2: write
    for m in M:
        if m.get('cut'): why['cut_part_excluded'] += 1; continue
        if BOLTS_ON and m.get('bolt'):
            bl_all = [bb for bb in BL if bb.get('pid') == m.get('pid')]
            bl = [bb for bb in bl_all if not bb.get('holes_only')]
            if bl_all and not bl:
                plist.append([m.get('pid'), m.get('prof'), 'feature', 'written', 'holes_only_group', None, 0]); src['holes_only_group'] += 1
                continue
            if bl:
                fitted = any(bb.get('shift') for bb in bl)
                std = bl[0].get('standard'); sg = bl[0].get('std')
                tags = []
                if not sg:
                    tags.append('head and nut nominal (1.6d across flats, 0.65d / 0.8d): no table for this standard/diameter')
                if not all(bb.get('tol') is not None for bb in bl):
                    tags.append('hole = d + standard clearance (tolerance not decoded)')
                if fitted:
                    tags.append('axial position fitted to the connected plies')
                if any(not bb.get('axial_decoded') for bb in bl) and not fitted:
                    tags.append('axial position as recorded (centred; offset fields absent)')
                if any(bb.get('wash_head') or bb.get('wash_nut') or bb.get('wash_2') for bb in bl):
                    if not all(db1bolts.washer_exact(bb) for bb in bl):
                        tags.append('washer thickness nominal')
                    if any(bb.get('wash_2') for bb in bl):
                        tags.append('washer 2 side inferred (flag digit 3)')
                if any(_c1_slot(bb) and bb.get('slot_state') != 'decoded' for bb in bl):   # tekla-slots: only undecoded groups stay round
                    tags.append('slotted holes cut as round holes (slotted parts not decoded)')
                nm = f"{m.get('prof')} {std or ''}" + (f" ({sg['family']}, {sg['mapping']})" if sg else '')
                e = out.bolt_group(_c1_name(nm, tags), bl)   # c1audit-stats
                plist.append([m.get('pid'), m.get('prof'), 'connection', 'written', 'bolt_group', e.GlobalId, 0]); src['bolt_group'] += 1
                continue
        b = bodies.get(id(m)) or body(m)
        if b[0] is None:
            why[b[1]] += 1; unres[m['prof'] or '<none>'] += 1
            plist.append([m.get('pid'), m.get('prof'), part_cat(m.get('prof'), b[1]), 'skipped', b[1], None, 0]); continue
        cuts = [cut_body[c] for c in cut_rel.get(m['pid'], []) if c in cut_body] if PART_CUTS_ON else []
        applied += len(cuts)
        if PART_CUTS_ON and FITP.get(id(m), (None, None))[1]:          # cut-not-applied P13: oblique fittings / line cuts
            size_ = 2.0 * (FITP[id(m)][0]['L'] + 2000.0)
            cuts = cuts + [_fit.halfspace_cut(out, P_, n_, size_) for P_, n_ in FITP[id(m)][1]]
            fit_stats['halfspaces_applied'] += len(FITP[id(m)][1])
        hc_ = []; near_ = 0.0
        for i in part_bolts.get(id(m), []):
            if (id(m), i) in inside:
                # not a ply: the bolt runs along the member (ROD48/ROD50 bars threaded through 60 mm holes-only groups) or lies wholly inside a
                # block; Tekla cuts only the bolted plies, so no hole here (code i bored the rods along their axis, a 60/70 mm hole severed them)
                holes_inside += 1; inside_prof[m.get('prof') or '?'] += 1; inside_why[inside[(id(m), i)]] += 1
                continue
            bb = BL[i]; dh, dec_ = db1bolts.hole_diameter(bb)
            if dh <= 0:                                          # tolerance <= -d: Tekla cuts no hole (STUD groups)
                holes_no_hole += 1
                continue
            holes_tol_decoded += 1 if dec_ else 0
            hole_src[bb.get('tol_status') or ('decoded' if dec_ else 'nominal')] += 1
            sset_ = SLOT_SET.get(bb.get('pid'), False) if SLOTS_ON else None
            sl_ = None                                           # tekla-slots: (slot x, slot y) when Tekla slots this ply
            if sset_ is None:
                holes_slot_round += 1 if any(x != 0 for x in (bb.get('slot') or ())) else 0
            elif sset_ and sset_.get(m.get('pid')):
                sl_ = tuple(abs(float(x)) for x in bb['slot']); slot_holes[0] += 1
                if (ROTP.get(bb.get('pid')) or {}).get(m.get('pid')):          # code v: Tekla 'rotate slots' in this ply
                    sl_ = (sl_[1], sl_[0]); slots_rotated[0] += 1
            ext = bb['L'] / 2 + 2 * bb['d']                      # through the whole grip (hole longer than the shank)
            c_ = np.asarray(bb['c'], float); ez_ = np.asarray(bb['ez'], float); mg_ = False; ex_ = np.asarray(bb['ex'], float)
            if HOLE_DEDUP:                                       # audit P6: a coaxial (< 1 mm) second hole is the same hole
                for h_ in hc_:
                    if abs(float(h_[1] @ ez_)) > 1 - 5e-7 and (sl_ is not None or h_[6] is not None or abs(h_[3] - dh) < 0.6):
                        w_ = c_ - h_[0]; s_ = float(w_ @ h_[1]); pp_ = float(np.linalg.norm(w_ - s_ * h_[1]))
                        if pp_ >= 1.0: continue
                        if not (s_ - ext < h_[5] and s_ + ext > h_[4]):
                            p6_apart[0] += 1; continue                # code q: coaxial but apart along the axis: two holes, cut separately
                        if sl_ is None and h_[6] is None:
                            near_ = max(near_, pp_, abs(h_[3] - dh)); h_[3] = max(h_[3], dh)
                            h_[4] = min(h_[4], s_ - ext); h_[5] = max(h_[5], s_ + ext); holes_merged[0] += 1; mg_ = True; break
                        # tekla-slots: a round hole wholly inside a coaxial slot is the slot; identical slots are one slot
                        if sl_ is None:
                            S_, r_, u_, cs_ = h_, dh / 2, w_, None
                        elif h_[6] is None:
                            S_, r_, u_, cs_ = None, h_[3] / 2, -w_, (c_, ex_, dh, sl_)
                        else:
                            if (abs(h_[3] - dh) < 1e-3 and max(abs(a - b) for a, b in zip(h_[6], sl_)) < 1e-3 and abs(float(h_[2] @ ex_)) > 1 - 1e-6
                                    and pp_ < 1e-3):
                                h_[4] = min(h_[4], s_ - ext); h_[5] = max(h_[5], s_ + ext); holes_merged[0] += 1; mg_ = True; break
                            continue
                        sc_, sx_, sd_, ss_ = (S_[0], S_[2], S_[3], S_[6]) if S_ is not None else cs_
                        ey_s = np.cross(ez_, sx_); u2_ = (c_ - sc_) if S_ is not None else (h_[0] - sc_)
                        du_, dv_ = abs(float(u2_ @ sx_)), abs(float(u2_ @ ey_s))
                        if du_ <= ss_[0] / 2 + 1e-6 and dv_ <= ss_[1] / 2 + 1e-6 and r_ <= sd_ / 2 + 1e-6:
                            if S_ is not None:
                                h_[4] = min(h_[4], s_ - ext); h_[5] = max(h_[5], s_ + ext)
                            else:                                # the slot replaces the round hole (origin moves to the slot centre)
                                lo0_, hi0_ = h_[4] - s_, h_[5] - s_
                                h_[0], h_[2], h_[3], h_[6] = c_, ex_, dh, sl_; h_[4] = min(lo0_, -ext); h_[5] = max(hi0_, ext)
                            holes_merged[0] += 1; mg_ = True; break
            if not mg_:
                hc_.append([c_, ez_, ex_, dh, -ext, ext, sl_])
            holes_cut += 1
        for h_ in hc_:
            if h_[6] is not None:                                # tekla-slots: slotted hole, long side along the group x / y axis
                key = ('S', round(h_[3], 3), round(h_[6][0], 3), round(h_[6][1], 3))
                if key not in hole_prof:
                    hole_prof[key] = out.profile('BOLT_SLOT_D%g_X%g_Y%g' % key[1:], 'RRECT', [h_[3] + h_[6][0], h_[3] + h_[6][1], h_[3] / 2])
                cuts = cuts + [((h_[0] + h_[1] * h_[4], h_[1], h_[2]), hole_prof[key], h_[5] - h_[4])]
                continue
            key = round(h_[3], 2)
            if key not in hole_prof:
                hole_prof[key] = out.profile('BOLT_HOLE_D%g' % key, 'CIRC', [h_[3] / 2])
            cuts = cuts + [((h_[0] + h_[1] * h_[4], h_[1], h_[2]), hole_prof[key], h_[5] - h_[4])]
        cat_ = part_cat(m.get('prof'), b[3])
        cls = 'IfcPlate' if cat_ in ('connection', 'other') and b[3] not in ('parametric_stud_shank', 'parametric_anchor') else (
              'IfcMechanicalFastener' if b[3] in ('parametric_stud_shank', 'parametric_anchor') else 'IfcBeam')
        nm_ = approx_name(m['prof'], b[3])
        if near_ >= 0.01:
            nm_ += f' [approx: coincident bolt holes merged ({near_:.2f} mm apart)]'; near_merged[0] += 1
        if id(m) in ARC:                                                      # arc patch: exact curved beam
            e = out.element_arc(cls, nm_ + ARC_TAG, ARC[id(m)], b[1], cuts)
        elif id(m) in POLY:
            e = out.element_poly(cls, nm_ + POLY_TAG, b[0], POLY[id(m)], b[1], cuts)
        else:
            e = out.element(cls, nm_, b[0], b[1], b[2], cuts)
        plist.append([m.get('pid'), m.get('prof'), cat_, 'written', b[3], e.GlobalId, len(cuts)])
        src[b[3]] += 1
    st['parts_list'] = plist
    # cut-not-applied P11: every cut part accounted for (the grade flag cuts_not_applied only sees unbuilt bodies)
    _wr = {p[0] for p in plist if p[3] == 'written'}; _lk = {c for v in cut_rel.values() for c in v}
    st['cut_stats'] = dict(cut_parts=sum(1 for m in M if m.get('cut')), bodies_built=len(cut_body), applied=applied,
                           unlinked=sum(1 for m in M if m.get('cut') and m['pid'] not in _lk),
                           links_to_unwritten_parts=sum(1 for p, cs in cut_rel.items() if p not in _wr for c in cs if c in cut_body),
                           operative_parts=sum(1 for m in M if m.get('cut') and m.get('mat') != 'ANTIMATERIAL'))
    hz = [m for m in M if not m.get('cut') and abs(m['x'][2]) < 0.1 and m['L'] > 500]
    yv = sum(1 for m in hz if abs(m['y'][2]) > 0.996) / len(hz) if hz else None
    st['fittings'] = dict(fit_stats, decoded=st['layout'].get('fittings_decoded'))      # cut-not-applied P13
    hzI = [m for m in hz if m.get('prof') and section_for(m['prof'], cat)[0] == 'I']
    yvI = sum(1 for m in hzI if abs(m['y'][2]) > 0.996) / len(hzI) if hzI else None
    if BOLTS_ON:
        hit = sum(1 for h in HI.hits if h > 0)
        st['bolt_stats'] = {'groups': src.get('bolt_group', 0), 'bolts': len(BL), 'holes_cut': holes_cut,
                            'bolts_with_holed_part': hit, 'bolts_without_holed_part': len(BL) - hit, **(ax_stats if BL else {}),
                            'holes_tolerance_decoded': holes_tol_decoded, 'holes_nominal_clearance': holes_cut - holes_tol_decoded,
                            'holes_by_diameter_source': dict(hole_src), 'holes_not_cut_zero_diameter': holes_no_hole,
                            'holes_in_slotted_groups_cut_round': holes_slot_round,
                            'holes_not_cut_bolt_inside_part': holes_inside, 'bolt_inside_part_why': dict(inside_why),
                            'bolt_inside_part_profiles': dict(inside_prof.most_common(10)),
                            'bolts_axial_decoded': sum(1 for bb in BL if bb.get('axial_decoded') and not bb.get('holes_only')),
                            'holes_only_bolts': sum(1 for bb in BL if bb.get('holes_only')),
                            'washers': sum((bb.get('wash_head') or 0) + (bb.get('wash_nut') or 0) + (bb.get('wash_2') or 0) for bb in BL if not bb.get('holes_only')),
                            'washers_nominal': sum((bb.get('wash_head') or 0) + (bb.get('wash_nut') or 0) + (bb.get('wash_2') or 0) for bb in BL
                                                   if not bb.get('holes_only') and not db1bolts.washer_exact(bb)),
                            'washer_side_inferred': sum(1 for bb in BL if not bb.get('holes_only') and bb.get('wash_2')),
                            'model_catalog_bolts': sum(1 for bb in BL if (bb.get('std') or {}).get('source') == 'model_catalog'),
                            'tekla_env_catalog': sum(1 for bb in BL if (bb.get('std') or {}).get('catalog_scope') == 'environment'),   # code r
                            'hole_diameter': 'stored bolt d + the group tolerance (field 4 of the bolt record, as stored: 0 / negative / > 10 included; d + t <= 0 = no hole); else d + standard clearance (AISC d + 1/16 in for ASTM, ISO 273 otherwise)',
                            'standards': dict(collections.Counter(bb.get('standard') or '?' for bb in BL)),
                            'standard_table_geometry': sum(1 for bb in BL if bb.get('std')),
                            'standard_mappings': dict(collections.Counter(f"{bb.get('standard')}: {bb['std']['mapping']} (delta {bb['std']['delta_mm']} mm)" for bb in BL if bb.get('std'))),
                            'nominal_head_nut_bolts': sum(1 for bb in BL if not bb.get('std')),
                            'nominal_head_nut_written': sum(1 for bb in BL if not bb.get('std') and not bb.get('holes_only')),   # c1audit-stats
                            'slotted_bolts_cut_round': sum(1 for bb in BL if _c1_slot(bb) and bb.get('slot_state') != 'decoded'),
                            'slotted_holes_cut': slot_holes[0], 'slot_groups': dict(slot_why), 'slots_rotated': slots_rotated[0],   # code v
                            'slot_rule': "attribute int @16 = Tekla 'slotted holes in part 1..5'; parts numbered by ply from the bolt head (Tekla NC validated); slot = rounded rectangle (d+tol+slot x) x (d+tol+slot y) along the group x / y axes" if SLOTS_ON else 'off',
                            'bolts_axial_unknown': sum(1 for bb in BL if not bb.get('holes_only') and not bb.get('axial_decoded') and not bb.get('shift')),
                            'writer': 'db1bolts (port of tekla-step-pipeline BuildBolt, positions identical) + axial fit to plies + clearance holes'}
    st['curved_beam_stats'] = dict(arc_stats)                            # arc patch
    st['audit_patch_stats'] = {'polybeam': dict(poly_stats), 'holes_merged': holes_merged[0], 'parts_with_near_coincident_holes_merged': near_merged[0],
                               'holes_not_bolted_dropped': dropped_holes[0], 'hole_rule': 'type-10 bolted parts within the grip' if HOLE_REL else 'geometric',
                               'coaxial_holes_apart_cut_separately': p6_apart[0], 'p4_list_fallback_geometric': p4_fallback[0] if BOLTS_ON and BL else 0,
                               'relations_10': len(getattr(db1old, 'REL', {}).get(10, [])), 'relations_11': len(getattr(db1old, 'REL', {}).get(11, [])),
                               'rect_plates_thin_side_to_z': sum(rect_thin_z.values()), 'rect_plate_names_reordered': dict(rect_thin_z.most_common(10))}
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
    elif not M and not info.get('part_attr'):
        st['status'] = 'empty_model'      # v2 (eng): no part records at all (7.30 model templates, 7-57 KB)
    else:
        st['status'] = 'no_resolvable_members' if M else 'no_member_layout'
    return st
