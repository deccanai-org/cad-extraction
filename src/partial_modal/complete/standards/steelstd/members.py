"""HSS (AISC / ASTM A500 corner radii, project-catalogue override) and reinforcing bars (ASTM A615, ACI 318 bends)."""
import math
import re

from . import geom as G
from . import tables as T
from .core import make_item

IN = T.IN


def _num(s):
    s = s.strip()
    if ' ' in s:
        a, b = s.split(' ', 1)
        return float(a) + T.f(b)
    return T.f(s) if '/' in s else float(s)


def parse_hss(name):
    """'HSS5x5x1/4' / 'HSS6X4X3/8' / 'HSS5.563x0.258' / 'HSS3-1/2X1-1/2X3/16' -> dict (inches) or None"""
    s = name.upper().replace('HSS', '', 1).strip().replace('-', ' ')
    parts = [p.strip() for p in s.split('X')]
    try:
        vals = [_num(p) for p in parts]
    except (ValueError, ZeroDivisionError):
        return None
    if len(vals) == 3:
        return {'shape': 'rect', 'H': vals[0], 'B': vals[1], 't': vals[2]}
    if len(vals) == 2:
        return {'shape': 'round', 'OD': vals[0], 't': vals[1]}
    return None


def hss_profile(name, *, t_rule='design', r_outer_mm=None, r_inner_mm=None, catalogue=None):
    """-> (profile dict for GEOM (mm), standard text, estimates list) or None.
    t_rule 'design' = AISC t_des = 0.93 t_nom (A500); 'nominal' = t_nom (A1085, or a catalogue that says so).
    r_outer_mm / r_inner_mm (+ catalogue = where they come from) override the AISC 2 t_des / t_des radii."""
    p = parse_hss(name)
    if p is None:
        return None
    t = p['t'] * (0.93 if t_rule == 'design' else 1.0)
    std = T.CITES['HSS_AISC']
    if p['shape'] == 'round':
        pr = {'kind': 'CHS', 'designation': name, 'radius': p['OD'] * IN / 2.0, 't': t * IN}
        return pr, f"{std}: {name}: OD {p['OD']:g} in, t_nom {p['t']:g} in -> t {t:.4f} in ({t_rule})", []
    ro = 2.0 * t * IN if r_outer_mm is None else float(r_outer_mm)
    ri = t * IN if r_inner_mm is None else float(r_inner_mm)
    pr = {'kind': 'RHS', 'designation': name, 'b': p['B'] * IN, 'd': p['H'] * IN, 't': t * IN, 'r_outer': ro,
          'r_inner': ri}
    txt = (f"{std}: {name}: H {p['H']:g} x B {p['B']:g} in, t_nom {p['t']:g} in -> t {t:.4f} in ({t_rule}), "
           + (f"r_outer {ro:.3f} mm, r_inner {ri:.3f} mm from {catalogue}" if r_outer_mm is not None
              else f"r_outer = 2 t = {2 * t:.4f} in, r_inner = t"))
    return pr, txt, []


def hss_member(name, start, end, x_dir, *, t_rule='design', r_outer_mm=None, r_inner_mm=None, catalogue=None,
               estimates=(), evidence=None, part_name=None):
    """straight HSS member (section centred on the start->end line; section b along x_dir, d along z x x_dir)"""
    r = hss_profile(name, t_rule=t_rule, r_outer_mm=r_outer_mm, r_inner_mm=r_inner_mm, catalogue=catalogue)
    if r is None:
        return None
    pr, txt, est = r
    g = G.profile_extrusion(pr, start, end, x_dir)
    L = G.norm(G.sub(G.v(end), G.v(start)))
    return make_item(g, f'{name} member, {L:.1f} mm', txt, list(estimates) + est, evidence,
                     simplifications=['weld seam not modelled'], name=part_name or name, designation=name,
                     role='member', ifc_class='IfcMember')


# ------------------------------------------------------------------ rebar


def rebar_size(designation):
    """'#5' / '5' / 'No. 5' / '16M' / '#16' (metric when > 18 or in REBAR_METRIC) -> (number, dia in, row) or None"""
    m = re.search(r'(\d+)', str(designation))
    if not m:
        return None
    n = int(m.group(1))
    metric = 'M' in str(designation).upper().replace('NO', '') or (n not in T.REBAR_A615 and n in T.REBAR_METRIC)
    if metric:
        n = T.REBAR_METRIC.get(n)
    if n not in T.REBAR_A615:
        return None
    return n, T.REBAR_A615[n][0], T.REBAR_A615[n]


def _bend_radius_db(n, kind):
    if kind == 'tie' and n <= 5:
        return 2.0          # inside diameter 4 db -> centreline radius 2 db + db/2 (added below)
    return 3.0 if n <= 8 else (4.0 if n <= 11 else 5.0)


def rebar(designation, points, *, bend='hook', seg_per_90=8, estimates=(), evidence=None, name=None):
    """straight (2 points) or bent bar (polyline corners rounded with the ACI 318 minimum inside bend diameter,
    arcs discretised into `seg_per_90` chords per 90 degrees; the sweep joints are mitred)"""
    r = rebar_size(designation)
    if r is None:
        return None
    n, db_in, row = r
    db = db_in * IN
    pts = [G.v(p) for p in points]
    std = (f"{T.CITES['REBAR_A615']}: #{n}: nominal dia {db_in:g} in, area {row[1]:g} in2, {row[2]:g} lb/ft"
           + (f"; {T.CITES['REBAR_BEND']}" if len(pts) > 2 else ''))
    simp = ['deformations (ribs) not modelled: plain bar of the nominal diameter (same nominal area / weight)']
    if len(pts) == 2:
        g = G.cylinder(pts[0], pts[1], db / 2.0)
    else:
        rc = (_bend_radius_db(n, bend) * db_in + db_in / 2.0) * IN      # centreline radius
        path = [pts[0]]
        for i in range(1, len(pts) - 1):
            a, b, c = pts[i - 1], pts[i], pts[i + 1]
            u1, u2 = G.unit(G.sub(b, a)), G.unit(G.sub(c, b))
            th = math.acos(max(-1.0, min(1.0, G.dot(u1, u2))))
            if th < 1e-6:
                path.append(b)
                continue
            tlen = rc * math.tan(th / 2.0)
            p1, p2 = G.sub(b, G.mul(u1, tlen)), G.add(b, G.mul(u2, tlen))
            nrm = G.unit(G.sub(u2, u1))
            ctr = G.add(b, G.mul(nrm, rc / math.cos(th / 2.0)))
            nseg = max(2, int(math.ceil(seg_per_90 * th / (math.pi / 2))))
            r1 = G.sub(p1, ctr)
            ax = G.unit(G.cross(u1, u2))
            for k in range(nseg + 1):
                phi = th * k / nseg
                rr = G.add(G.mul(r1, math.cos(phi)), G.add(G.mul(G.cross(ax, r1), math.sin(phi)),
                                                       G.mul(ax, G.dot(ax, r1) * (1 - math.cos(phi)))))
                path.append(G.add(ctr, rr))
            del p2
        path.append(pts[-1])
        g = G.sweep({'kind': 'CIRCLE', 'radius': db / 2.0}, path)
        simp.append(f'bends: {seg_per_90} chords per 90 deg (mitred sweep)')
    return make_item(g, f'reinforcing bar #{n} (ASTM A615)', std, estimates, evidence, simplifications=simp,
                     name=name or f'REBAR #{n}', designation=f'#{n}', role='other', ifc_class='IfcReinforcingBar')
