"""Bolts (ASTM F3125 A325/A490 heavy hex, A307 hex), nuts (A563), washers (F436), bolt length (RCSC), holes (AISC J3.3),
headed studs (AWS D1.1), anchor rods (F1554 + AISC Table 14-2). All lengths in: mm in / mm out as named.

Bolt frame: `origin` = the point on the outer ply face where the head (or the head-side washer) bears, `axis` = unit
vector from the head into the plies (the shank direction); the plies occupy 0 <= s <= grip along `axis`.
"""
import math
import re

from . import geom as G
from . import tables as T
from .core import make_item

IN = T.IN

HEAVY_RE = re.compile(r'^(ASTM)?(A325|A490|F3125|F1852|F2280|A325[NXSC]+|A490[NXSC]+)')


def bolt_family(standard):
    """bolt standard string -> 'heavy_hex' | 'hex' | None (unknown)"""
    s = (standard or '').upper().replace(' ', '').replace('-', '').replace('_', '')
    if HEAVY_RE.match(s) or s.startswith(('A325', 'A490', 'F3125', 'F1852', 'F2280', 'TC')):
        return 'heavy_hex'
    if s.startswith(('A307', 'ASTMA307')):
        return 'hex'
    return None


def bolt_dims(family, d_in):
    """-> {'d', 'head_F', 'head_H', 'nut_F', 'nut_H', 'rows', 'standard'} in inches, or None (no table row)"""
    if family == 'heavy_hex':
        k = T.nearest(T.HEAVY_HEX_BOLT, d_in)
        if k is None or k not in T.HEAVY_HEX_NUT:
            return None
        F, H, thr = T.HEAVY_HEX_BOLT[k]
        nF, nH = T.HEAVY_HEX_NUT[k]
        std = (f"{T.CITES['HEAVY_HEX_BOLT']}: D={T.frac(k)} in F={T.frac(F)} H={T.frac(H)}; "
               f"{T.CITES['HEAVY_HEX_NUT']}: F={T.frac(nF)} H={T.frac(nH)}")
        return {'d': k, 'head_F': F, 'head_H': H, 'nut_F': nF, 'nut_H': nH, 'thread': thr, 'standard': std,
                'rows': {'HEAVY_HEX_BOLT': k, 'HEAVY_HEX_NUT': k}}
    if family == 'hex':
        k = T.nearest(T.HEX_BOLT, d_in)
        if k is None or k not in T.HEX_NUT:
            return None
        F, H = T.HEX_BOLT[k]
        nF, nH = T.HEX_NUT[k]
        std = (f"{T.CITES['HEX_BOLT']}: D={T.frac(k)} in F={T.frac(F)} H={T.frac(H)}; "
               f"{T.CITES['HEX_NUT']}: F={T.frac(nF)} H={T.frac(nH)}")
        return {'d': k, 'head_F': F, 'head_H': H, 'nut_F': nF, 'nut_H': nH, 'thread': None, 'standard': std,
                'rows': {'HEX_BOLT': k, 'HEX_NUT': k}}
    return None


def washer_dims(d_in):
    """F436 circular washer -> (ID, OD, t) inches + citation, or None"""
    k = T.nearest(T.F436_WASHER, d_in)
    if k is None:
        return None
    ID, OD, tmin, tmax = T.F436_WASHER[k]
    t = T.F436_FLAT_ALLOWANCE if 0.5 <= k <= 1.5 else round((tmin + tmax) / 2.0, 4)
    return ID, OD, t, (f"{T.CITES['F436_WASHER']}: D={T.frac(k)} in ID={T.frac(ID)} OD={T.frac(OD)} "
                       f"t={tmin}-{tmax} (modelled {t:.4f})")


def bolt_length(d_in, grip_in, n_washers=0):
    """RCSC Table C-2.2 rule -> (L in, text) or None when the diameter has no row"""
    k = T.nearest(T.GRIP_ADD, d_in)
    if k is None:
        return None
    raw = grip_in + T.GRIP_ADD[k] + n_washers * T.F436_FLAT_ALLOWANCE
    step = 0.25 if raw <= 5.0 else 0.5
    L = math.ceil(raw / step - 1e-9) * step
    return L, (f"{T.CITES['GRIP_ADD']}: grip {grip_in:.4f} + {T.frac(T.GRIP_ADD[k])}"
               + (f" + {n_washers} x 5/32" if n_washers else '') + f" = {raw:.4f} -> L = {L:g} in")


def bolt_length_small(d_in, grip_in, nut_H_in, n_washers=0, washer_t_in=0.0):
    """no RCSC row (D < 1/2 in): L = grip + washers + nut + 3 thread pitches (UNC), rounded up to 1/4 in.
    An extrapolation of the RCSC rule's intent (full nut engagement + stick-out) -> the caller marks it estimated."""
    unc = {0.25: 20, 0.3125: 18, 0.375: 16, 0.4375: 14}
    tpi = unc.get(T.nearest(unc, d_in), 16)
    raw = grip_in + n_washers * washer_t_in + nut_H_in + 3.0 / tpi
    L = math.ceil(raw / 0.25 - 1e-9) * 0.25
    return L, (f"no RCSC Table C-2.2 row below 1/2 in: L = grip {grip_in:.4f} + nut {nut_H_in:.4f} + 3 x 1/{tpi} "
               f"(UNC pitch) = {raw:.4f} -> {L:g} in (rounded up to 1/4 in)")


def hole_dims(d_in, kind='standard'):
    """AISC 360-16 Table J3.3 -> (width, length) inches (round: width = length = diameter)"""
    k = T.nearest(T.HOLES_J3_3, d_in)
    if k is None:
        if d_in >= 1.125 - 1e-6:
            w = d_in + 1 / 16
            return {'standard': (w, w), 'oversize': (d_in + 5 / 16,) * 2, 'short_slot': (w, d_in + 3 / 8),
                    'long_slot': (w, 2.5 * d_in)}[kind]
        return None
    std, ovs, ss, ls = T.HOLES_J3_3[k]
    return {'standard': (std, std), 'oversize': (ovs, ovs), 'short_slot': ss, 'long_slot': ls}[kind]


# ------------------------------------------------------------------ assemblies


def bolt_assembly(origin, axis, d_in, grip_mm, family, *, x_dir=None, length_in=None, washers_head=0, washers_nut=0,
                  nut=True, estimates=(), evidence=None, name=None, family_source='data'):
    """heavy hex / hex bolt + nut (+ F436 washers) as one compound part. Returns a StdItem or None (no table row).
    family_source: 'data' (the source names the grade) or an estimate text (then the item is AMBER)."""
    dims = bolt_dims(family, d_in)
    if dims is None:
        return None
    est = list(estimates)
    if family_source != 'data':
        est.append(family_source)
    a = G.unit(axis)
    o = G.v(origin)
    d = dims['d'] * IN
    grip_in = grip_mm / IN
    wd = washer_dims(dims['d']) if (washers_head or washers_nut) else None
    if (washers_head or washers_nut) and wd is None:
        return None
    tw = wd[2] * IN if wd else 0.0
    std = [dims['standard']]
    ev = {'d_in': dims['d'], 'grip_in': round(grip_in, 4), 'family': family, 'rows': dims['rows']}
    if length_in is None:
        if family == 'heavy_hex' and T.nearest(T.GRIP_ADD, dims['d']) is not None:
            L_in, txt = bolt_length(dims['d'], grip_in, washers_head + washers_nut)
            std.append(txt)
        else:
            L_in, txt = bolt_length_small(dims['d'], grip_in, dims['nut_H'], washers_head + washers_nut,
                                          wd[2] if wd else 0.0)
            est.append('bolt length ' + txt)
        ev['length_rule'] = txt
    else:
        L_in = float(length_in)
        ev['length_in_source'] = L_in
    L = L_in * IN
    s0 = -washers_head * tw                                   # head bearing face
    items = []
    head = G.hex_prism(G.add(o, G.mul(a, s0)), G.mul(a, -1.0), dims['head_H'] * IN, dims['head_F'] * IN, x_dir)
    items.append(head)
    items.append(G.cylinder(G.add(o, G.mul(a, s0)), G.add(o, G.mul(a, s0 + L)), d / 2.0))
    for i in range(washers_head):
        items.append(G.ring(G.add(o, G.mul(a, -(i + 1) * tw)), a, tw, wd[1] * IN, wd[0] * IN))
    s = grip_mm
    for i in range(washers_nut):
        items.append(G.ring(G.add(o, G.mul(a, s)), a, tw, wd[1] * IN, wd[0] * IN))
        s += tw
    if wd:
        std.append(wd[3])
    if nut:
        nut_end = s + dims['nut_H'] * IN
        if nut_end > s0 + L + 1e-6:
            est.append(f'bolt length {L_in:g} in is shorter than grip + washers + nut ({(nut_end - s0) / IN:.3f} in): '
                       'nut drawn on the full thread anyway')
        items.append(G.hex_prism(G.add(o, G.mul(a, s)), a, dims['nut_H'] * IN, dims['nut_F'] * IN, x_dir,
                                 hole_diameter=d))
    fam_txt = {'heavy_hex': 'heavy hex structural bolt + A563 heavy hex nut', 'hex': 'A307 hex bolt + hex nut'}[family]
    nm = name or f"BOLT {T.frac(dims['d'])} x {L_in:g} {fam_txt.split(' + ')[0]}"
    what = (f"{fam_txt}, D {T.frac(dims['d'])} in, L {L_in:g} in, grip {grip_in:.4f} in"
            + (f", {washers_head + washers_nut} F436 washer(s)" if (washers_head or washers_nut) else ', no washers'))
    return make_item(G.compound(items), what, ' | '.join(std), est, dict(ev, **(evidence or {})),
                     simplifications=['threads not modelled (shank = nominal diameter cylinder)',
                                      'head / nut chamfers and washer faces not modelled'],
                     name=nm, designation=f"{T.frac(dims['d'])}", role='bolt', ifc_class='IfcMechanicalFastener')


def headed_stud(base, axis, d_in, length_in, *, estimates=(), evidence=None, name=None):
    """AWS D1.1 headed stud: `base` = centre of the welded end on the steel surface, `axis` = out of the steel,
    `length_in` = length after welding (the installed length, head included)."""
    k = T.nearest(T.STUDS, d_in)
    if k is None:
        return None
    Hd, Th, src = T.STUDS[k]
    a = G.unit(axis)
    o = G.v(base)
    L = length_in * IN
    sh = L - Th * IN
    items = [G.cylinder(o, G.add(o, G.mul(a, sh)), k * IN / 2.0),
             G.cylinder(G.add(o, G.mul(a, sh)), G.add(o, G.mul(a, L)), Hd * IN / 2.0)]
    std = f"{T.CITES[src]}: C={T.frac(k)} in head dia {Hd:g} in, head height {Th:g} in (minimum)"
    return make_item(G.compound(items), f'headed stud {T.frac(k)} x {length_in:g} in (after weld)', std, estimates,
                     dict({'d_in': k, 'length_in': length_in}, **(evidence or {})),
                     simplifications=['weld fillet (flash) at the base not modelled', 'head height = the table minimum'],
                     name=name or f'STUD {T.frac(k)} x {length_in:g}', designation=f'{T.frac(k)}', role='accessory')


def anchor_rod(top, axis_down, d_in, length_in, *, projection_in, end='headed', washer=True, leveling_nut=False,
               plate_t_in=0.0, x_dir=None, estimates=(), evidence=None, name=None):
    """ASTM F1554 anchor rod: `top` = the top end of the rod, `axis_down` = into the concrete; `projection_in` = from
    the top of concrete to the top end; nut + AISC Table 14-2 plate washer on the base plate (top of plate =
    top of concrete + plate_t); end = 'headed' (heavy hex nut at the bottom) or 'hooked' (90 deg hook 4.5 d long).
    """
    nut = T.HEAVY_HEX_NUT.get(T.nearest(T.HEAVY_HEX_NUT, d_in))
    k = T.nearest(T.ANCHOR_14_2, d_in)
    if nut is None or (washer and k is None):
        return None
    d = d_in * IN
    a = G.unit(axis_down)
    o = G.v(top)
    L = length_in * IN
    est = list(estimates)
    std = [f"{T.CITES['HEAVY_HEX_NUT']}: D={T.frac(d_in)} F={T.frac(nut[0])} H={T.frac(nut[1])}"]
    toc = projection_in * IN                                   # top of concrete, s from the top end
    plate_top = toc - plate_t_in * IN
    items = []
    if end == 'hooked':
        eh = 4.5 * d
        straight = L - eh
        items.append(G.cylinder(o, G.add(o, G.mul(a, straight)), d / 2.0))
        h = G.square_to(x_dir or G.perp(a), a)
        foot = G.add(o, G.mul(a, straight - d / 2.0))
        items.append(G.cylinder(foot, G.add(foot, G.mul(h, eh)), d / 2.0))
        std.append(T.CITES['ANCHOR_14_2'].split('; ')[-1])
        est.append('hook length 4.5 d (ACI 318 upper limit) and hook direction')
    else:
        items.append(G.cylinder(o, G.add(o, G.mul(a, L)), d / 2.0))
        items.append(G.hex_prism(G.add(o, G.mul(a, L - nut[1] * IN)), a, nut[1] * IN, nut[0] * IN, x_dir,
                                 hole_diameter=d))
    s = plate_top
    if washer:
        hole, wmin, wt = T.ANCHOR_14_2[k]
        wt_mm, ws = wt * IN, wmin * IN
        x = G.square_to(x_dir or G.perp(a), a)
        y = G.cross(a, x)
        c = G.add(o, G.mul(a, s - wt_mm))
        corner = G.add(c, G.add(G.mul(x, -ws / 2), G.mul(y, -ws / 2)))
        pw = G.box(corner, x, y, [ws, ws, wt_mm])
        pw['cuts'] = [{'kind': 'solid', 'tool': G.cylinder(G.add(c, G.mul(a, -1.0)), G.add(c, G.mul(a, wt_mm + 1.0)),
                                                             (d + IN / 16) / 2.0)}]
        items.append(pw)
        std.append(f"{T.CITES['ANCHOR_14_2']}: rod {T.frac(d_in)} in: washer {wmin:g} x {wmin:g} x {T.frac(wt)} in, "
                   f"washer hole d + 1/16 in")
        s -= wt_mm
    items.append(G.hex_prism(G.add(o, G.mul(a, s)), G.mul(a, -1.0), nut[1] * IN, nut[0] * IN, x_dir, hole_diameter=d))
    if leveling_nut:
        items.append(G.hex_prism(G.add(o, G.mul(a, plate_top + plate_t_in * IN)), a, nut[1] * IN, nut[0] * IN,
                                 x_dir, hole_diameter=d))
        est.append('leveling nut directly under the base plate (grout gap not known)')
    g = G.compound(items)
    vol = G.volume(g)
    if washer:
        vol -= math.pi * ((d + IN / 16) / 2.0) ** 2 * T.ANCHOR_14_2[k][2] * IN
    it = make_item(g, f'anchor rod {T.frac(d_in)} x {length_in:g} in ({end}), F1554', ' | '.join(std), est,
                   dict({'d_in': d_in, 'length_in': length_in}, **(evidence or {})),
                   simplifications=['threads not modelled'], name=name or f'ANCHOR ROD {T.frac(d_in)} x {length_in:g}',
                   designation=T.frac(d_in), role='bolt')
    it['target']['volume_mm3'] = round(vol, 3)
    return it
