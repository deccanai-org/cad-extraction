"""Welded steel bar grating panels (NAAMM ANSI/NAAMM MBG 531): bearing bars on a fixed pitch, cross bars on a fixed
pitch flush with the top, optional end bands. The panel is a rectangle in its own frame: length along the bearing bars,
width across them, depth = bearing bar height (from the source).

The type (bearing-bar pitch / cross-bar pitch), bar thickness, banding and the cross-bar section come from the source
only when it states them (a designation like '19-W-4 1 1/2 x 3/16', or the source's own bar records); every value the
caller did not get from the source is an ESTIMATE (AMBER, listed in the basis). A stated piece weight is the check.
"""
import math
import re

from . import geom as G
from . import tables as T
from .core import make_item

IN = T.IN
LB_PER_MM3 = 0.2836 / IN ** 3


def parse_grating(name):
    """-> {'type', 'depth_in', 'bar_t_in'} for what the name states (may be empty)"""
    s = str(name).upper()
    out = {}
    m = re.search(r'(\d+)-W-(\d+)', s)
    if m and f'{m.group(1)}-W-{m.group(2)}' in T.GRATING_TYPES:
        out['type'] = f'{m.group(1)}-W-{m.group(2)}'
        m2 = re.search(r'(\d+(?:[ -]\d+/\d+)?|\d+/\d+)\s*X\s*(\d+/\d+)', s[m.end():])
        if m2:
            out['depth_in'] = T.f(m2.group(1).replace(' ', '-'))
            out['bar_t_in'] = T.f(m2.group(2))
    return out


def grating_panel(origin, u, w_dir, length_mm, width_mm, depth_mm, *, gtype=None, bar_t_in=None, bar_first_mm=None,
                  cross_first_mm=None, cross_size_in=None, end_band_t_in=0.0, source_weight_lb=None, known=(),
                  name=None, designation='', evidence=None, extra_estimates=()):
    """origin = panel corner (u = 0, v = 0, bottom), u = bearing-bar direction, w_dir = up (bar height), v = w x u.
    known: the parameter names the caller measured from the source ('type', 'bar_t', 'bar_first', 'cross_first',
    'cross_size', 'end_band'); every other default is listed as an estimate."""
    u, w = G.unit(u), G.unit(w_dir)
    u = G.unit(G.sub(u, G.mul(w, G.dot(u, w))))
    vv = G.cross(w, u)
    o = G.v(origin)
    known = set(known)
    est = list(extra_estimates)
    if gtype is None:
        gtype = '19-W-4'
    if 'type' not in known:
        est.append('grating type 19-W-4 (bearing bars at 1 3/16 in, cross bars at 4 in centres: the NAAMM MBG 531 '
                   'type most used) - the source does not state the type')
    if bar_t_in is None:
        bar_t_in = 3 / 16
    if 'bar_t' not in known:
        est.append(f'bearing bar thickness {T.frac(bar_t_in)} in - the source does not state it')
    cs = cross_size_in or T.GRATING_CROSS_BAR
    if 'cross_size' not in known:
        est.append(f'cross bar {T.frac(cs)} in square (the usual welded-grating cross bar; its section is the '
                   'manufacturer\'s) - the source does not give it')
    bb_pitch, cb_pitch = T.GRATING_TYPES[gtype]
    t, pb, pc, c = bar_t_in * IN, bb_pitch * IN, cb_pitch * IN, cs * IN
    eb = end_band_t_in * IN
    if bar_first_mm is None:
        nb = int(math.floor((width_mm - t) / pb + 1e-9)) + 1
        y0 = (width_mm - ((nb - 1) * pb + t)) / 2.0
    else:
        y0 = bar_first_mm
        nb = int(math.floor((width_mm - y0 - t) / pb + 1e-6)) + 1
    ys = [y0 + i * pb for i in range(nb)]
    x_lo, x_hi = eb, length_mm - eb
    if cross_first_mm is None:
        nc = int(math.floor((x_hi - x_lo - c) / pc + 1e-9)) + 1
        x0 = x_lo + (x_hi - x_lo - ((nc - 1) * pc + c)) / 2.0
    else:
        x0 = cross_first_mm
        nc = int(math.floor((x_hi - x0 - c) / pc + 1e-6)) + 1
    xs = [x0 + j * pc for j in range(nc)]
    items = []

    def bx(xa, ya, za, dx, dy, dz):
        return G.box(G.add(o, G.add(G.mul(u, xa), G.add(G.mul(vv, ya), G.mul(w, za)))), u, vv, [dx, dy, dz])

    for ya in ys:
        items.append(bx(x_lo, ya, 0.0, x_hi - x_lo, t, depth_mm))
    if eb > 0:
        items.append(bx(0.0, 0.0, 0.0, eb, width_mm, depth_mm))
        items.append(bx(length_mm - eb, 0.0, 0.0, eb, width_mm, depth_mm))
    gaps = [(ys[i] + t, ys[i + 1]) for i in range(nb - 1)]
    if ys[0] > 0.5:
        gaps = [(0.0, ys[0])] + gaps
    if width_mm - (ys[-1] + t) > 0.5:
        gaps = gaps + [(ys[-1] + t, width_mm)]
    for xa in xs:
        for a, b in gaps:
            items.append(bx(xa, a, depth_mm - c, c, b - a, c))
    comp = G.compound(items)
    lb = G.volume(comp) * LB_PER_MM3
    std = (f"{T.CITES['NAAMM_MBG531']}: type {gtype}: bearing bars {depth_mm / IN:.4g} x {T.frac(bar_t_in)} in at "
           f"{T.frac(bb_pitch)} in, cross bars {T.frac(cs)} in sq at {cb_pitch:g} in"
           + (f', end bands {T.frac(end_band_t_in)} in' if eb else ''))
    ev = {'type': gtype, 'bearing_bars': nb, 'cross_bars': nc, 'first_bar_mm': round(ys[0], 3),
          'first_cross_bar_mm': round(xs[0], 3), 'weight_lb_model': round(lb, 2), 'measured_from_source': sorted(known)}
    if source_weight_lb:
        ev['weight_lb_source'] = source_weight_lb
        ev['weight_ratio_model_to_source'] = round(lb / source_weight_lb, 4)
    ev.update(evidence or {})
    simp = ['cross bars modelled as straight square bars (twist not modelled), flush with the top']
    if not eb:
        simp.append('no banding bars (the source does not record banding)')
    return make_item(comp, f'bar grating {gtype} {depth_mm / IN:.4g} x {T.frac(bar_t_in)} in, '
                           f'{length_mm:.1f} x {width_mm:.1f} mm ({nb} bearing bars, {nc} cross bars)',
                     std, est, ev, simplifications=simp, name=name or f'GRATING {gtype}',
                     designation=designation or gtype, role='plate', ifc_class='IfcPlate')
