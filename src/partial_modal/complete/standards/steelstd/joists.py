"""SJI open-web steel joists (K / KCS / LH / DLH) from the designation.

What SJI fixes (BLUE parts of the reasoning): nominal depth = designation number (in.), standard end bearing depth
(K / KCS 2 1/2 in, LH / DLH 5 in), the K-series approximate weight per foot (load table). What SJI does NOT fix: the
chord and web sizes and the panel layout (each manufacturer designs them). So a joist built here is always AMBER:
the chord / web sizes are ESTIMATED so the joist weighs the SJI approximate weight, with double-angle chords, a
Warren web of round bars and a nominal 24 in panel - the usual K-series make-up - and the basis says so.
"""
import math
import re

from . import geom as G
from . import tables as T
from .core import make_item

IN = T.IN


def parse_joist(designation):
    m = re.match(r'^\s*(\d+)\s*(KCS|K|LH|DLH)\s*(\d+)\s*$', str(designation).upper())
    if not m:
        return None
    return {'depth_in': float(m.group(1)), 'series': m.group(2), 'section': int(m.group(3))}


def _angle_area(b, t):
    return t * (2 * b - t)


def _angle_centroid(b, t):
    """distance of an equal-leg angle's centroid from the heel (outer face of either leg)"""
    return (b * b + b * t - t * t) / (2.0 * (2.0 * b - t))


def _angle_t(b, area):
    """thickness of an equal-leg angle of leg b with the given area"""
    return b - math.sqrt(max(b * b - area, 0.0))


def joist(designation, p1, p2, up, *, weight_plf=None, panel_in=24.0, seat_len_in=4.0, evidence=None, name=None):
    """p1, p2 = the two ends of the joist's top-of-top-chord line (the SDS/2 / Tekla work line at the joist top),
    up = the joist's vertical. Returns a StdItem (AMBER) or None (unparseable designation)."""
    j = parse_joist(designation)
    if j is None:
        return None
    D = j['depth_in']
    seat = T.SJI_SEAT_DEPTH[j['series']]
    est, std = [], [f"{T.CITES['SJI_K']}: {designation}: depth {D:g} in, end bearing depth {seat:g} in"]
    W = weight_plf
    if W is None:
        W = T.SJI_K_WEIGHT.get(designation.upper().replace(' ', '')) if j['series'] in ('K', 'KCS') else None
        if W is not None:
            std.append(f'SJI K-Series load table approximate weight {W:g} lb/ft (the chord sizes are fitted to it)')
        else:
            W = 0.35 * D + 1.0 if j['series'] in ('K', 'KCS') else 0.6 * D
            est.append(f'weight {W:.1f} lb/ft from a depth rule (designation not in the transcribed SJI weight table)')
    b = 1.25 if D <= 20 else (1.5 if D <= 30 else (2.0 if D <= 48 else 3.0))     # chord angle leg (in)
    A = W / T.LB_PER_FT_PER_IN2                                                 # total section area per ft (in2)
    t_tc = round(_angle_t(b, 0.40 * A / 2.0), 4)
    t_bc = round(_angle_t(b, 0.32 * A / 2.0), 4)
    yc_tc, yc_bc = _angle_centroid(b, t_tc), _angle_centroid(b, t_bc)
    h = D - yc_tc - yc_bc                                                       # chord centroid distance
    p1, p2, up = G.v(p1), G.v(p2), G.unit(up)
    xs = G.unit(G.sub(p2, p1))
    xs = G.unit(G.sub(xs, G.mul(up, G.dot(xs, up))))
    Ltot = G.dot(G.sub(p2, p1), xs) / IN
    ys = G.cross(up, xs)
    P = G.frame(p1, xs, ys, up)                                                 # (x along span, y lateral, z up), in -> mm via k()

    def k(x, y, z):
        return P(x * IN, y * IN, z * IN)

    e0 = seat_len_in
    xb0 = e0 + 0.6 * h
    n = max(1, int(math.ceil((Ltot - 2 * xb0) / panel_in - 1e-9)))          # panels no longer than panel_in
    p = (Ltot - 2 * xb0) / n
    if p <= 0:
        return None
    # web bars: Warren, BC(0) -> TC(0.5) -> BC(1) ... + the two end diagonals; bar length per ft sets its diameter
    zt, zb = -yc_tc, -D + yc_bc
    nodes = [(e0, zt), (xb0, zb)]
    for i in range(n):
        nodes += [(xb0 + (i + 0.5) * p, zt), (xb0 + (i + 1) * p, zb)]
    nodes.append((Ltot - e0, zt))
    web_len = sum(math.hypot(nodes[i + 1][0] - nodes[i][0], nodes[i + 1][1] - nodes[i][1]) for i in range(len(nodes) - 1))
    A_web = 0.28 * A * (Ltot / 12.0) * 12.0 / web_len                          # 28 % of the weight in the web
    dw = round(math.sqrt(4.0 * A_web / math.pi), 4)
    g = dw                                                                      # gap between the angles = web bar
    items = []

    def angle(y0, sgn, z0, zdir, t, x0, x1, bv=None):
        # angle with its heel at (y0, z0): horizontal leg b towards sgn*y, vertical leg bv (default b) towards zdir
        bv = b if bv is None else bv
        pts = [(y0, z0), (y0 + sgn * b, z0), (y0 + sgn * b, z0 + zdir * t), (y0 + sgn * t, z0 + zdir * t),
               (y0 + sgn * t, z0 + zdir * bv), (y0, z0 + zdir * bv)]
        return G.prism([k(x0, yy, zz) for yy, zz in pts], xs, (x1 - x0) * IN)

    for sgn in (1, -1):
        items.append(angle(sgn * g / 2, sgn, 0.0, -1, t_tc, 0.0, Ltot))                 # top chord
        items.append(angle(sgn * g / 2, sgn, -D, 1, t_bc, xb0, Ltot - xb0))             # bottom chord
    ts = 0.25
    for x0 in (0.0, Ltot - seat_len_in):                                                # bearing seats
        for sgn in (1, -1):
            y0 = sgn * (g / 2 + t_tc)
            items.append(angle(y0, sgn, -seat, 1, ts, x0, x0 + seat_len_in, bv=seat - t_tc))
    for i in range(len(nodes) - 1):
        (xa, za), (xb, zb_) = nodes[i], nodes[i + 1]
        items.append(G.cylinder(k(xa, 0.0, za), k(xb, 0.0, zb_), dw * IN / 2.0))
    comp = G.compound(items)
    wt = G.volume(comp) / (IN ** 3) * 0.2836 / (Ltot / 12.0)
    est += [f'chords 2L{b:g}x{b:g}x{t_tc:.3f} (top) / 2L{b:g}x{b:g}x{t_bc:.3f} (bottom), web round bars dia {dw:.3f} in, '
            f'Warren web on {n} panels of {p:.2f} in (<= {panel_in:g} in), seats 2L{b:g}x{seat - t_tc:.2f}x1/4 x {seat_len_in:g} in: sized so '
            f'the joist weighs the SJI approximate weight ({wt:.2f} vs {W:g} lb/ft); SJI leaves chords / webs to the '
            f'manufacturer', 'overall length = the work-line length (no top chord extension recorded)']
    ev = {'designation': designation, 'depth_in': D, 'seat_depth_in': seat, 'weight_plf_target': W,
          'weight_plf_model': round(wt, 3), 'span_in': round(Ltot, 3), 'panels': n, 'panel_in': round(p, 3)}
    ev.update(evidence or {})
    return make_item(comp, f'open-web steel joist {designation} (SJI), {Ltot:.2f} in', ' | '.join(std), est, ev,
                     simplifications=['angle root / toe radii not modelled', 'bridging not modelled'],
                     name=name or f'JOIST {designation}', designation=designation, role='member', ifc_class='IfcBeam')
