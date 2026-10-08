"""GEOM records (complete/INTERFACES.md section 2.4, world mm) + their exact volume / bounding box (pure Python, so a
patch carries a `target` the integration checks its build against) + a build123d reference builder used by the unit
tests (same semantics as complete/integrate/completion_core.geom_rows -> steelbuild).

Kinds emitted by this library: cylinder, hex_prism, ring, prism, box, compound.
"""
import math

# ------------------------------------------------------------------ vectors


def v(a):
    return [float(a[0]), float(a[1]), float(a[2])]


def add(a, b):
    return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]


def sub(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def mul(a, k):
    return [a[0] * k, a[1] * k, a[2] * k]


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def norm(a):
    return math.sqrt(dot(a, a))


def unit(a):
    n = norm(a)
    if n < 1e-12:
        raise ValueError('zero vector')
    return mul(a, 1.0 / n)


def perp(z):
    """a unit vector square to z (deterministic)"""
    z = unit(z)
    t = [1.0, 0.0, 0.0] if abs(z[0]) < 0.9 else [0.0, 1.0, 0.0]
    return unit(sub(t, mul(z, dot(t, z))))


def square_to(x, z):
    """x made square to z (falls back to perp(z))"""
    z = unit(z)
    if x is None:
        return perp(z)
    x = sub(v(x), mul(z, dot(v(x), z)))
    return unit(x) if norm(x) > 1e-9 else perp(z)


def frame(o, x, y, z):
    """local (u, v, w) -> world point"""
    return lambda u, vv, w: add(o, add(mul(x, u), add(mul(y, vv), mul(z, w))))


def r9(p):
    return [round(c, 6) for c in p]


# ------------------------------------------------------------------ GEOM constructors


def cylinder(start, end, radius):
    return {'kind': 'cylinder', 'start': r9(start), 'end': r9(end), 'radius': round(float(radius), 6)}


def hex_prism(base_center, axis, height, across_flats, x_dir=None, hole_diameter=None):
    g = {'kind': 'hex_prism', 'base_center': r9(base_center), 'axis': r9(unit(axis)), 'height': round(float(height), 6),
         'across_flats': round(float(across_flats), 6)}
    if x_dir is not None:
        g['x_dir'] = r9(square_to(x_dir, axis))
    if hole_diameter:
        g['hole_diameter'] = round(float(hole_diameter), 6)
    return g


def ring(base_center, axis, height, outer_diameter, inner_diameter):
    return {'kind': 'ring', 'base_center': r9(base_center), 'axis': r9(unit(axis)), 'height': round(float(height), 6),
            'outer_diameter': round(float(outer_diameter), 6), 'inner_diameter': round(float(inner_diameter), 6)}


def prism(outline_world, normal, thickness):
    return {'kind': 'prism', 'outline_world': [r9(p) for p in outline_world], 'normal': r9(unit(normal)),
            'thickness': round(float(thickness), 6)}


def box(origin, x_dir, y_dir, size):
    return {'kind': 'box', 'origin': r9(origin), 'x_dir': r9(unit(x_dir)), 'y_dir': r9(unit(y_dir)),
            'size': [round(float(s), 6) for s in size]}


def profile_extrusion(profile, start, end, x_dir):
    return {'kind': 'profile_extrusion', 'profile': dict(profile), 'start': r9(start), 'end': r9(end),
            'x_dir': r9(square_to(x_dir, sub(end, start)))}


def sweep(profile, points, x_dir=None):
    g = {'kind': 'sweep', 'profile': dict(profile), 'points': [r9(p) for p in points]}
    if x_dir is not None:
        g['x_dir'] = r9(x_dir)
    return g


def section_area(pr):
    k = pr['kind']
    if k == 'RHS':
        B, D, t, ri, ro = pr['b'], pr['d'], pr['t'], pr.get('r_inner', 0.0), pr.get('r_outer', 0.0)
        return (B * D - (4 - math.pi) * ro ** 2) - ((B - 2 * t) * (D - 2 * t) - (4 - math.pi) * ri ** 2)
    if k == 'CHS':
        return math.pi * (pr['radius'] ** 2 - (pr['radius'] - pr['t']) ** 2)
    if k == 'CIRCLE':
        return math.pi * pr['radius'] ** 2
    if k == 'RECT':
        return pr['b'] * pr['d'] - (4 - math.pi) * pr.get('r_outer', 0.0) ** 2
    raise ValueError(k)


def compound(items):
    return {'kind': 'compound', 'items': list(items)}


# ------------------------------------------------------------------ exact volume and bounding box


def _poly_area_normal(pts, n):
    """area of a planar polygon (world points) projected on unit normal n (Newell)"""
    s = [0.0, 0.0, 0.0]
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        s = add(s, cross(a, b))
    return abs(dot(s, n)) / 2.0


def _hex_vertices(g):
    z = unit(g['axis'])
    x = square_to(g.get('x_dir'), z)
    y = cross(z, x)
    R = g['across_flats'] / math.sqrt(3.0)
    out = []
    for k in range(6):
        a = math.pi / 6 + k * math.pi / 3
        out.append(add(g['base_center'], add(mul(x, R * math.cos(a)), mul(y, R * math.sin(a)))))
    return out, z


def volume(g):
    k = g['kind']
    if k == 'compound':
        return sum(volume(i) for i in g['items'])
    if k == 'cylinder':
        return math.pi * g['radius'] ** 2 * norm(sub(g['end'], g['start']))
    if k == 'hex_prism':
        a = math.sqrt(3.0) / 2.0 * g['across_flats'] ** 2
        if g.get('hole_diameter'):
            a -= math.pi * g['hole_diameter'] ** 2 / 4.0
        return a * g['height']
    if k == 'ring':
        return math.pi / 4.0 * (g['outer_diameter'] ** 2 - g['inner_diameter'] ** 2) * g['height']
    if k == 'prism':
        return _poly_area_normal(g['outline_world'], unit(g['normal'])) * g['thickness']
    if k == 'box':
        return g['size'][0] * g['size'][1] * g['size'][2]
    if k == 'profile_extrusion':
        return section_area(g['profile']) * norm(sub(g['end'], g['start']))
    if k == 'sweep':
        p = g['points']
        return section_area(g['profile']) * sum(norm(sub(p[i + 1], p[i])) for i in range(len(p) - 1))
    raise ValueError(k)


def bbox(g):
    """exact axis-aligned bounding box [x0, y0, z0, x1, y1, z1]"""
    k = g['kind']
    if k == 'compound':
        bs = [bbox(i) for i in g['items']]
        return [min(b[i] for b in bs) for i in range(3)] + [max(b[i + 3] for b in bs) for i in range(3)]
    if k in ('cylinder', 'ring'):
        if k == 'cylinder':
            s, e, r = g['start'], g['end'], g['radius']
        else:
            s = g['base_center']
            e = add(s, mul(unit(g['axis']), g['height']))
            r = g['outer_diameter'] / 2.0
        a = unit(sub(e, s))
        ext = [r * math.sqrt(max(0.0, 1.0 - a[i] ** 2)) for i in range(3)]
        return [min(s[i], e[i]) - ext[i] for i in range(3)] + [max(s[i], e[i]) + ext[i] for i in range(3)]
    if k == 'profile_extrusion':
        pr, s_, e_ = g['profile'], g['start'], g['end']
        z = unit(sub(e_, s_))
        x = square_to(g.get('x_dir'), z)
        y = cross(z, x)
        if pr['kind'] in ('CHS', 'CIRCLE'):
            return bbox(cylinder(s_, e_, pr['radius']))
        ro = pr.get('r_outer', 0.0) or 0.0
        hb, hd = pr['b'] / 2.0 - ro, pr['d'] / 2.0 - ro
        pts = [add(c, add(mul(x, i * hb), mul(y, j * hd))) for c in (s_, e_) for i in (-1, 1) for j in (-1, 1)]
        ext = [ro * math.sqrt(max(0.0, 1.0 - z[i] ** 2)) for i in range(3)]
        return ([min(p[i] for p in pts) - ext[i] for i in range(3)] + [max(p[i] for p in pts) + ext[i] for i in range(3)])
    if k == 'hex_prism':
        vs, z = _hex_vertices(g)
        pts = vs + [add(p, mul(z, g['height'])) for p in vs]
    elif k == 'prism':
        n = unit(g['normal'])
        pts = list(g['outline_world']) + [add(p, mul(n, g['thickness'])) for p in g['outline_world']]
    elif k == 'box':
        x = unit(g['x_dir'])
        y = unit(sub(g['y_dir'], mul(x, dot(x, g['y_dir']))))
        z = cross(x, y)
        dx, dy, dz = g['size']
        pts = [add(g['origin'], add(mul(x, i * dx), add(mul(y, j * dy), mul(z, l * dz))))
               for i in (0, 1) for j in (0, 1) for l in (0, 1)]
    else:
        raise ValueError(k)
    return [min(p[i] for p in pts) for i in range(3)] + [max(p[i] for p in pts) for i in range(3)]


def n_solids(g):
    return len(g['items']) if g['kind'] == 'compound' else 1


def _has_sweep(g):
    return g['kind'] == 'sweep' or (g['kind'] == 'compound' and any(i['kind'] == 'sweep' for i in g['items']))


def target(g, tol_rel=0.005, tol_mm=0.5):
    t = {'volume_mm3': round(volume(g), 3), 'tol_rel': tol_rel, 'tol_mm': tol_mm}
    if not _has_sweep(g):            # a mitred sweep's exact box is not computed here: volume only
        t['bbox'] = [round(c, 4) for c in bbox(g)]
    return t


# ------------------------------------------------------------------ build123d reference builder (tests only)


def to_shape(g):
    """GEOM -> build123d Solid / Compound (lazy import: the patch makers never need the CAD kernel)"""
    from build123d import Solid, Compound, Plane, Vector, Face, Wire, Edge, Polyline, extrude, Location  # noqa: F401
    k = g['kind']
    if k == 'compound':
        return Compound(children=[to_shape(i) for i in g['items']])
    if k == 'cylinder':
        s, e = g['start'], g['end']
        h = norm(sub(e, s))
        pl = Plane(origin=Vector(*s), x_dir=Vector(*perp(sub(e, s))), z_dir=Vector(*unit(sub(e, s))))
        return Solid.make_cylinder(g['radius'], h, pl)
    if k == 'hex_prism':
        vs, z = _hex_vertices(g)
        f = Face(Wire.make_polygon([Vector(*p) for p in vs], close=True))
        sol = Solid.extrude(f, Vector(*mul(z, g['height'])))
        if g.get('hole_diameter'):
            hole = to_shape(cylinder(add(g['base_center'], mul(z, -1.0)),
                                     add(g['base_center'], mul(z, g['height'] + 1.0)), g['hole_diameter'] / 2.0))
            sol = sol.cut(hole)
            sol = sol.solids()[0] if hasattr(sol, 'solids') else sol
        return sol
    if k == 'ring':
        z = unit(g['axis'])
        pl = Plane(origin=Vector(*g['base_center']), x_dir=Vector(*perp(z)), z_dir=Vector(*z))
        outer = Solid.make_cylinder(g['outer_diameter'] / 2.0, g['height'], pl)
        inner = Solid.make_cylinder(g['inner_diameter'] / 2.0, g['height'], pl)
        r = outer.cut(inner)
        return r.solids()[0] if hasattr(r, 'solids') else r
    if k == 'prism':
        n = unit(g['normal'])
        f = Face(Wire.make_polygon([Vector(*p) for p in g['outline_world']], close=True))
        return Solid.extrude(f, Vector(*mul(n, g['thickness'])))
    if k == 'box':
        x = unit(g['x_dir'])
        y = unit(sub(g['y_dir'], mul(x, dot(x, g['y_dir']))))
        z = cross(x, y)
        pl = Plane(origin=Vector(*g['origin']), x_dir=Vector(*x), z_dir=Vector(*z))
        dx, dy, dz = g['size']
        sol = Solid.make_box(dx, dy, dz, pl)
        for c in g.get('cuts') or []:
            r = sol.cut(to_shape(c['tool']))
            sol = r.solids()[0] if hasattr(r, 'solids') else r
        return sol
    if k == 'profile_extrusion':
        from build123d import RectangleRounded, Rectangle, Circle
        pr, s_, e_ = g['profile'], g['start'], g['end']
        z = unit(sub(e_, s_))
        x = square_to(g.get('x_dir'), z)
        pl = Plane(origin=Vector(*s_), x_dir=Vector(*x), z_dir=Vector(*z))
        if pr['kind'] == 'RHS':
            def rr(b, d, r):
                return RectangleRounded(b, d, r) if r > 1e-9 else Rectangle(b, d)
            sec = rr(pr['b'], pr['d'], pr.get('r_outer', 0.0)) - rr(pr['b'] - 2 * pr['t'], pr['d'] - 2 * pr['t'],
                                                                     pr.get('r_inner', 0.0))
        elif pr['kind'] == 'CHS':
            sec = Circle(pr['radius']) - Circle(pr['radius'] - pr['t'])
        else:
            raise ValueError(pr['kind'])
        face = (pl * sec).faces()[0]
        return Solid.extrude(face, Vector(*sub(e_, s_)))
    raise ValueError(k)
