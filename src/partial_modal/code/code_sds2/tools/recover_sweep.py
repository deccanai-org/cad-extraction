#!/usr/bin/env python3
"""Recover faceted parts that are a polygon section swept along a polyline path: bent anchor rods and bars, bent pipes
and rails, welds along edges, around corners and all round, studs and bolts (a section at several sizes along a
straight path). Used by recover.py when the straight-extrusion test fails.

A faceted solid is a sweep when its faces form a tube (decided on the topology alone, then confirmed on the geometry):

  * end caps: two faces (open path) or none (closed path, every face a quad);
  * between them rings of vertices, ring k+1 reached from ring k through one strip of quads (a segment): every quad
    has one edge on each ring, its two other edges join corresponding vertices of the two rings;
  * every ring lies in one plane (the joint plane), the lateral edges of one segment are parallel (the segment is a
    straight prism between its two joint planes) - or, for a section at two sizes, meet in one point (a frustum).

The section is then the same all along the path, either square to every segment (section "perpendicular": a
classic sweep, mitred joints) or on every joint plane (section "joint": faceted bends, where the source places the
profile itself on each joint plane). The rewrite is

    profile (NGON when the section is a regular polygon, else a POLY outline of exact source vertices)
    + path (paths.json: the profile origin, i.e. the section's area centroid, at every ring) + the joint planes that
      are not the rule (mitre / square end) + the scale at every ring where the section changes size

and the solid rebuilt from those schedule rows by steelbuild (the code the client runs) must pass recover.coincide -
the acceptance test of every recovered part (recover.py) - and, stricter still, every source vertex must have a rebuilt
vertex within VTOL and vice versa. A one-segment tube is a straight prism: it is written as a plain extrusion with plane
cuts at oblique ends (no path).

try_sweep(rec) -> (candidates | None, reason); candidates follow recover.try_part's format plus 'path' (for paths.json).
"""
import collections
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'kit'))

VTOL = 0.02              # mm: a rebuilt vertex and a source vertex coincide (the source sits on a 0.01 mm grid)
PAR_TOL = 0.03           # mm: a lateral edge's deviation from its segment's direction
PLANE_TOL = 0.02         # mm: ring vertices off their joint plane
SEC_TOL = 0.03           # mm: the section's vertices from one segment (ring) to the next
LINE_TOL = 0.01          # mm: path points this close to one straight line lie on it (a straight axis)
MAX_FACES = 4000


# ======================================================================================== topology
def topology(faces):
    """faces [[outer, hole, ...], ...] of 3D points -> (V: unique vertices (n x 3), F: faces as lists of vertex-id loops)"""
    key, V, F = {}, [], []
    for fc in faces:
        loops = []
        for lp in fc:
            ids = []
            for p in lp:
                k = (round(p[0], 4), round(p[1], 4), round(p[2], 4))
                if k not in key:
                    key[k] = len(V)
                    V.append(p)
                if not ids or ids[-1] != key[k]:
                    ids.append(key[k])
            while len(ids) > 1 and ids[0] == ids[-1]:
                ids.pop()
            if len(ids) >= 3:
                loops.append(ids)
        F.append(loops)
    return np.asarray(V, float), F


def _e(a, b):
    return (a, b) if a < b else (b, a)


def edge_map(F):
    E = collections.defaultdict(list)
    for fi, loops in enumerate(F):
        for lp in loops:
            for i in range(len(lp)):
                E[_e(lp[i], lp[(i + 1) % len(lp)])].append(fi)
    return E


def _quad(F, f):
    return F[f][0] if len(F[f]) == 1 and len(F[f][0]) == 4 else None


def _step_partner(V, F, f, cycle):
    """face f is an annulus with `cycle` as one of its two loops (a shoulder: the section changes size in place) ->
    its other loop, started and run so that its vertex i lies in the direction of the cycle's vertex i (or None)"""
    if V is None or len(F[f]) != 2:
        return None
    lo = [lp for lp in F[f] if set(lp) != set(cycle)]
    if len(lo) != 1 or len(lo[0]) != len(cycle):
        return None
    o, n = lo[0], len(cycle)
    ctr = V[cycle].mean(0)
    a = V[cycle] - ctr
    b = V[o] - ctr
    a = a / np.linalg.norm(a, axis=1)[:, None]
    b = b / np.linalg.norm(b, axis=1)[:, None]
    best = None
    for sgn in (1, -1):
        for r in range(n):
            idx = [(r + sgn * i) % n for i in range(n)]
            err = float(np.sum(1.0 - np.einsum('ij,ij->i', a, b[idx])))
            if best is None or err < best[0] - 1e-12:
                best = (err, idx)
    if best[0] > n * 1e-4:                                # corners not in the same directions: not a scaled copy
        return None
    return [o[i] for i in best[1]]


def _advance(F, E, cycles, prev, V=None):
    """one step along the tube from a ring (vertex cycles; prev = the face each ring edge was reached from)
    -> ('cap', face) | ('ring', next cycles, next prev, quads of the segment) | ('step', next cycles, next prev, {face})
    | (None, reason)"""
    across = {}
    for c in cycles:
        for i in range(len(c)):
            e = _e(c[i], c[(i + 1) % len(c)])
            fs = E.get(e, [])
            if len(fs) != 2 or fs[0] == fs[1]:
                return None, 'not a closed manifold'
            across[e] = fs[0] if fs[1] == prev[e] else fs[1]
    fset = set(across.values())
    if len(fset) == 1:
        f = next(iter(fset))
        fe = {_e(lp[i], lp[(i + 1) % len(lp)]) for lp in F[f] for i in range(len(lp))}
        if fe == set(across):
            return 'cap', f
        if len(cycles) == 1:
            o = _step_partner(V, F, f, cycles[0])
            if o is not None:
                return 'step', [o], {_e(o[i], o[(i + 1) % len(o)]): f for i in range(len(o))}, {f}
    succ, nprev, quads = {}, {}, set()
    for c in cycles:
        for i in range(len(c)):
            a, b = c[i], c[(i + 1) % len(c)]
            f = across[_e(a, b)]
            q = _quad(F, f)
            if q is None or a not in q or b not in q:
                return None, 'not a strip of quads'
            ia, ib = q.index(a), q.index(b)
            if ib == (ia + 1) % 4:
                sa, sb = q[(ia - 1) % 4], q[(ib + 1) % 4]
            elif ia == (ib + 1) % 4:
                sa, sb = q[(ia + 1) % 4], q[(ib - 1) % 4]
            else:
                return None, 'not a strip of quads'
            for v, s in ((a, sa), (b, sb)):
                if succ.setdefault(v, s) != s:
                    return None, 'not a strip of quads'
            quads.add(f)
    nxt = [[succ[v] for v in c] for c in cycles]
    flat = [v for c in nxt for v in c]
    if len(set(flat)) != len(flat) or set(flat) & {v for c in cycles for v in c}:
        return None, 'not a strip of quads'
    for c, cn in zip(cycles, nxt):
        for i in range(len(c)):
            nprev[_e(cn[i], cn[(i + 1) % len(cn)])] = across[_e(c[i], c[(i + 1) % len(c)])]
    return 'ring', nxt, nprev, quads


def march_open(F, E, cap, V=None):
    """rings of an open tube starting at face `cap` -> ([ring, ...], other cap) | (None, reason). With V, an annular
    face whose loops are two sizes of the ring (a shoulder) is a step: its outer and inner loop are consecutive rings"""
    cycles = [list(lp) for lp in F[cap]]
    prev = {_e(lp[i], lp[(i + 1) % len(lp)]): cap for lp in cycles for i in range(len(lp))}
    rings, used = [cycles], {cap}
    while True:
        r = _advance(F, E, cycles, prev, V)
        if r[0] is None:
            return None, r[1]
        if r[0] == 'cap':
            if r[1] in used:
                return None, 'not a tube'
            used.add(r[1])
            other = r[1]
            break
        _, cycles, prev, quads = r
        if quads & used:
            return None, 'not a tube'
        used |= quads
        rings.append(cycles)
        if len(rings) > len(F):
            return None, 'not a tube'
    if len(used) != len(F):
        return None, 'faces outside the tube'
    # the last ring must be the other cap's loops (same cycles)
    return rings, other


def _straight_walk(F, E, adj, a, b):
    """from edge a-b keep going straight through valence-4 vertices (the edge opposite a-b) back to a"""
    cyc = [a, b]
    while True:
        u, v = cyc[-2], cyc[-1]
        if len(adj[v]) != 4:
            return None
        fu = set(E[_e(u, v)])
        cand = [w for w in sorted(adj[v]) if w != u and not (set(E[_e(v, w)]) & fu)]
        if len(cand) != 1:
            return None
        w = cand[0]
        if w == cyc[0]:
            return cyc
        if w in cyc or len(cyc) > len(adj):
            return None
        cyc.append(w)


def march_closed(F, E):
    """rings of a closed tube (every face a quad, no caps) -> [ring, ...] | (None, reason)"""
    adj = collections.defaultdict(set)
    for (a, b) in E:
        adj[a].add(b)
        adj[b].add(a)
    q0 = next((f for f in range(len(F)) if _quad(F, f)), None)
    if q0 is None:
        return None, 'no quads'
    q = _quad(F, q0)
    for h in (0, 1):
        ring = _straight_walk(F, E, adj, q[h], q[h + 1])
        if ring is None:
            continue
        # the faces on one side of the ring (q0's side), edge by edge
        prev = {_e(ring[0], ring[1]): q0}
        f = q0
        ok = True
        for i in range(1, len(ring)):
            a, b = ring[i], ring[(i + 1) % len(ring)]
            qq = _quad(F, f)
            k = qq.index(a)
            y = qq[(k + 1) % 4] if qq[(k - 1) % 4] == ring[i - 1] else qq[(k - 1) % 4]   # the lateral neighbour of a in f
            g = [x for x in E[_e(a, b)] if _e(a, y) in {_e(qx[j], qx[(j + 1) % 4]) for qx in [_quad(F, x)] if qx for j in range(4)}]
            if len(g) != 1:
                ok = False
                break
            prev[_e(a, b)] = g[0]
            f = g[0]
        if not ok:
            continue
        cycles = [ring]
        rings, used = [cycles], set()
        good = False
        while True:
            r = _advance(F, E, cycles, prev)
            if r[0] != 'ring':
                break
            _, cycles, prev, quads = r
            if quads & used:
                break
            used |= quads
            if cycles[0] == ring:
                good = len(used) == len(F)
                break
            if set(cycles[0]) == set(ring):
                break                                   # back on the first ring, but rotated (a twisted tube)
            rings.append(cycles)
            if len(rings) > len(F):
                break
        if good and len(rings) >= 3:
            return rings, None
    return None, 'not a closed tube'


def find_tube(faces):
    """-> (V, rings (list of rings, each a list of vertex cycles: outer loop first), closed, reason)"""
    V, F = topology(faces)
    if any(not f for f in F):
        return V, None, False, 'degenerate face'
    E = edge_map(F)
    if any(len(v) != 2 for v in E.values()):
        return V, None, False, 'not a closed manifold'
    others = [f for f in range(len(F)) if _quad(F, f) is None]
    caps = [f for f in others if len(F[f]) == 1]
    if len(others) == 2 or (len(caps) == 2 and all(len(F[f]) == 2 for f in others if f not in caps)):
        r = march_open(F, E, caps[0] if len(caps) == 2 else others[0], V)
        if r[0] is not None and r[1] == (caps[1] if len(caps) == 2 else others[1]):
            return V, r[0], False, None
        return V, None, False, r[1] if r[0] is None else 'not a tube'
    if others:
        return V, None, False, 'not a tube (%d faces besides quads)' % len(others)
    r = march_closed(F, E)
    if r[0] is not None:
        return V, r[0], True, None
    # every face a quad: a four-sided section, caps unknown. Every face is tried as a cap; of the tubes found the one
    # with the most rings wins, then the largest side area (the natural extrusion axis, as recover.find_axis), then
    # the first in face order
    area = []
    for f in range(len(F)):
        q = V[F[f][0]]
        area.append(0.5 * np.linalg.norm(newell(q)))
    best, seen = None, set()
    for f in range(len(F)):
        if f in seen:
            continue
        r = march_open(F, E, f)
        if r[0] is None:
            continue
        seen.add(r[1])
        side = sum(area) - area[f] - area[r[1]]
        key = (len(r[0]), side)
        if best is None or key > best[0]:
            best = (key, r[0])
    if best is not None:
        return V, best[1], False, None
    return V, None, False, 'not a tube'


# ======================================================================================== geometry
def _unit(v):
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else None


def newell(p):
    q = np.roll(p, -1, axis=0)
    return np.array([np.sum((p[:, 1] - q[:, 1]) * (p[:, 2] + q[:, 2])), np.sum((p[:, 2] - q[:, 2]) * (p[:, 0] + q[:, 0])),
                     np.sum((p[:, 0] - q[:, 0]) * (p[:, 1] + q[:, 1]))])


def carry(x, a, b):
    """x turned by the smallest rotation taking unit a to unit b (as steelbuild._carry)"""
    k = np.cross(a, b)
    s, c = np.linalg.norm(k), float(np.dot(a, b))
    if s < 1e-12:
        return x if c > 0 else None
    k = k / s
    return x * c + np.cross(k, x) * s + k * (np.dot(k, x) * (1 - c))


def area_centroid(p):
    """area and centroid of a closed 2D polygon"""
    x, y = p[:, 0], p[:, 1]
    x1, y1 = np.roll(x, -1), np.roll(y, -1)
    cr = x * y1 - x1 * y
    a = cr.sum() / 2.0
    if abs(a) < 1e-12:
        return 0.0, p.mean(0)
    return a, np.array([((x + x1) * cr).sum() / (6 * a), ((y + y1) * cr).sum() / (6 * a)])


def sections(R, sizes, frames, origins_from='centroid'):
    """2D sections (list of loops) of 3D point sets R[k] in the frames (o-less): (normal z, x axis) -> centred 2D arrays"""
    out = []
    for P, (z, x) in zip(R, frames):
        y = np.cross(z, x)
        Q = np.stack([P @ x, P @ y], 1)
        loops, i = [], 0
        for s in sizes:
            loops.append(Q[i:i + s])
            i += s
        a, c = area_centroid(loops[0])
        out.append((Q - c, c, a))
    return out


def analyse(V, rings, closed):
    """geometry of a topological tube -> dict (mode, section 2D, frames, points, normals ...) or (None, reason)"""
    sizes = [len(c) for c in rings[0]]
    R = [np.concatenate([V[c] for c in ring]) for ring in rings]
    nr = len(R)
    m = nr if closed else nr - 1
    seg = [(k, (k + 1) % nr) for k in range(m)]
    d, par, worst = [], [], 0.0
    for i, j in seg:
        L = R[j] - R[i]
        ni = _unit(newell(V[rings[i][0]]))
        if (ni is not None and np.linalg.norm(R[j].mean(0) - R[i].mean(0)) <= PLANE_TOL
                and np.abs((R[j] - R[i].mean(0)) @ ni).max() <= PLANE_TOL):
            d.append(None)                      # a step: the section changes size in place (a shoulder)
            par.append('step')
            continue
        dk = _unit(L.sum(0))
        if dk is None:
            return None, 'degenerate segment'
        dev = np.linalg.norm(L - np.outer(L @ dk, dk), axis=1).max()
        if (L @ dk).min() <= 0:
            return None, 'not a sweep (segment folds back)'
        d.append(dk)
        par.append(bool(dev <= PAR_TOL))        # a prism; otherwise possibly a frustum between scaled sections
        worst = max(worst, dev)
    if all(x == 'step' for x in par):
        return None, 'not a sweep (no length)'
    for k in range(m):                          # a step runs in the direction of the segment before it (else after)
        if d[k] is None:
            d[k] = next((d[q] for q in range(k - 1, -1, -1) if d[q] is not None), None)
            if d[k] is None:
                d[k] = next(d[q] for q in range(k + 1, m) if d[q] is not None)
    rn, rc = [], []
    for k in range(nr):
        n = _unit(newell(V[rings[k][0]]))
        if n is None:
            return None, 'degenerate ring'
        c = R[k].mean(0)
        dev = np.abs((R[k] - c) @ n).max()
        if dev > PLANE_TOL:
            return None, 'not a sweep (ring not planar, %.3f mm)' % dev
        ref = d[k] if (closed or k < m) else d[m - 1]
        if np.dot(n, ref) < 0:
            n = -n
        if np.dot(n, ref) < 0.05:
            return None, 'not a sweep (joint plane along the path)'
        rn.append(n)
        rc.append(c)
    # provisional section x axis: the first outer edge, square to the first section normal
    def carried(normals):
        x = V[rings[0][0][1]] - V[rings[0][0][0]]
        x = _unit(x - normals[0] * np.dot(x, normals[0]))
        if x is None:
            return None
        xs = [x]
        for k in range(1, len(normals)):
            x = carry(xs[-1], normals[k - 1], normals[k])
            if x is None:
                return None
            x = _unit(x - normals[k] * np.dot(x, normals[k]))
            xs.append(x)
        return xs
    result = None
    if not all(x is True for x in par):
        return _analyse_scaled(V, rings, closed, R, sizes, seg, m, d, par, worst, rn, rc, carried)
    # (a) perpendicular: every segment's section square to it (projection of its start ring along the segment)
    xs = carried(d)
    if xs is not None:
        S = sections([R[i] for i, j in seg], sizes, list(zip(d, xs)))
        dev = max(np.abs(s[0] - S[0][0]).max() for s in S)
        S2 = sections([R[j] for i, j in seg], sizes, list(zip(d, xs)))
        dev = max(dev, max(np.abs(s[0] - S[0][0]).max() for s in S2))
        if dev <= SEC_TOL:
            result = dict(mode='perpendicular', secn=d, xs=xs, S=S + S2, dev=dev)
    if result is None:
        # (b) joint: the section on every segment's start joint plane (rings 0..m-1; for an open path the last ring too,
        # which is the last segment trimmed by the end plane)
        nrm = [rn[i] for i, j in seg]
        xs = carried(nrm)
        if xs is None:
            return None, 'not a sweep (path turns back)'
        S = sections([R[i] for i, j in seg], sizes, list(zip(nrm, xs)))
        dev = max(np.abs(s[0] - S[0][0]).max() for s in S)
        if not closed:
            xl = carry(xs[-1], nrm[-1], rn[-1])
            xl = _unit(xl - rn[-1] * np.dot(xl, rn[-1]))
            Sl = sections([R[-1]], sizes, [(rn[-1], xl)])
            dev = max(dev, np.abs(Sl[0][0] - S[0][0]).max())
            S = S + Sl
        if dev > SEC_TOL:
            return None, 'not a sweep (section changes along the path, %.3f mm)' % dev
        result = dict(mode='joint', secn=nrm, xs=xs, S=S, dev=dev)
    result.update(d=d, rn=rn, rc=rc, R=R, sizes=sizes, seg=seg, m=m, closed=closed)
    return result, None


def _analyse_scaled(V, rings, closed, R, sizes, seg, m, d, par, worst, rn, rc, carried):
    """(c) joint with scales: an open path whose rings are one polygon at different sizes, on the joint planes; a
    segment between two rings of the same size is a prism, between two sizes a frustum (corner-to-corner ruled faces)"""
    if closed:
        return None, 'not a sweep (segment edges not parallel, %.3f mm)' % worst
    nrm = list(rn)                                        # every ring on its own joint plane
    xs = carried(nrm)
    if xs is None:
        return None, 'not a sweep (path turns back)'
    S = sections(R, sizes, list(zip(nrm, xs)))
    a0 = S[0][2]
    if any(s[2] * a0 <= 0 for s in S):
        return None, 'not a sweep (section flips)'
    sc = [math.sqrt(s[2] / a0) for s in S]
    group = [0]                                           # rings joined by prisms have one size
    for k, (i, j) in enumerate(seg):
        if par[k] == 'step':
            if abs(sc[j] - sc[i]) <= 1e-3 * sc[i]:
                return None, 'not a sweep (step without a change of size)'
            group.append(group[-1] + 1)
        elif par[k]:
            if abs(sc[j] - sc[i]) > 1e-3 * sc[i]:
                return None, 'not a sweep (prism between sections of different size)'
            group.append(group[-1])
        elif abs(sc[j] - sc[i]) <= 1e-3 * sc[i]:
            return None, 'not a sweep (segment edges not parallel, %.3f mm)' % worst
        else:
            group.append(group[-1] + 1)
    P2 = [s[0] for s in S]
    for _ in range(3):                                    # least squares: one profile, one scale per size group
        prof = np.mean([q / sc[k] for k, q in enumerate(P2)], axis=0)
        pp = float((prof * prof).sum())
        g_sc = {}
        for g in sorted(set(group)):
            ks = [k for k in range(len(P2)) if group[k] == g]
            g_sc[g] = sum(float((P2[k] * prof).sum()) for k in ks) / (pp * len(ks))
        sc = [g_sc[group[k]] / g_sc[group[0]] for k in range(len(P2))]
    Q = [q / f for q, f in zip(P2, sc)]
    Qm = np.mean(Q, axis=0)
    dev = max(np.abs(q - Qm).max() * f for q, f in zip(Q, sc))
    if dev > SEC_TOL:
        return None, 'not a sweep (section changes along the path, %.3f mm)' % dev
    res = dict(mode='joint', secn=nrm[:m], xs=xs[:m], S=S, scales=sc, dev=dev, par=par)
    res.update(d=d, rn=rn, rc=rc, R=R, sizes=sizes, seg=seg, m=m, closed=closed)
    return res, None


def _line_point(c, dvec, o, n):
    """intersection of the line c + t dvec with the plane through o with normal n"""
    return c + dvec * (np.dot(o - c, n) / np.dot(dvec, n))


def _closest_mid(c1, d1, c2, d2):
    """midpoint of the closest points of two lines"""
    w = c1 - c2
    a, b, c = np.dot(d1, d1), np.dot(d1, d2), np.dot(d2, d2)
    dd, e = np.dot(d1, w), np.dot(d2, w)
    den = a * c - b * b
    if abs(den) < 1e-12:
        return None
    s = (b * e - c * dd) / den
    t = (a * e - b * dd) / den
    return (c1 + s * d1 + c2 + t * d2) / 2.0


def candidate(A):
    """analysis -> schedule rows: profile (NGON) or outline (POLY), frame, path, cuts"""
    import recover
    mode, d, rn, seg, m, closed = A['mode'], A['d'], A['rn'], A['seg'], A['m'], A['closed']
    sizes = A['sizes']
    scl = A.get('scales') or [1.0] * len(A['S'])
    S = np.mean([s[0] / f for s, f in zip(A['S'], scl)], axis=0)   # the section, averaged over the path, centred on its centroid
    loops, i = [], 0
    for s in sizes:
        loops.append(S[i:i + s])
        i += s
    # canonical section x axis: towards vertex 0 of a regular polygon, else along the longest outer edge
    ng = recover.regular_polygon(loops[0], loops[1:])
    if ng:
        ang = math.atan2(loops[0][0][1], loops[0][0][0])
    else:
        o = loops[0]
        el = np.linalg.norm(np.roll(o, -1, 0) - o, axis=1)
        k = int(np.argmax(el >= el.max() * (1 - 1e-9)))
        v = o[(k + 1) % len(o)] - o[k]
        ang = math.atan2(v[1], v[0])
    ca, sa = math.cos(ang), math.sin(ang)
    rot = lambda p: np.stack([p[:, 0] * ca + p[:, 1] * sa, -p[:, 0] * sa + p[:, 1] * ca], 1)
    loops = [rot(p) for p in loops]
    z0, x0p = A['secn'][0], A['xs'][0]
    y0p = np.cross(z0, x0p)
    x0 = x0p * ca + y0p * sa
    # path: the section centroid at every ring
    cen = []                                               # 3D centroid point on each segment's reference line
    for k, (i, j) in enumerate(seg):
        _, c2, _ = A['S'][k]
        z, x = A['secn'][k], A['xs'][k]
        y = np.cross(z, x)
        P = A['R'][i]
        cen.append(x * c2[0] + y * c2[1] + z * np.dot(P.mean(0), z))
    pts = []
    if mode == 'perpendicular':
        n_pts = m if closed else m + 1
        for k in range(n_pts):
            if not closed and k == 0:
                pts.append(_line_point(cen[0], d[0], A['rc'][0], rn[0]))
            elif not closed and k == m:
                pts.append(_line_point(cen[m - 1], d[m - 1], A['rc'][m], rn[m]))
            else:
                p = _closest_mid(cen[k - 1], d[k - 1], cen[k % m], d[k % m])
                if p is None:
                    return None, 'collinear segments'
                pts.append(p)
    else:
        for k in range(len(A['R'])):
            if k < m:
                z, x = A['secn'][k], A['xs'][k]
                _, c2, _ = A['S'][k]
            else:                                            # last ring of an open path
                z = rn[k]
                x = carry(A['xs'][-1], A['secn'][-1], z)
                x = _unit(x - z * np.dot(x, z))
                _, c2, _ = A['S'][-1]
            y = np.cross(z, x)
            pts.append(x * c2[0] + y * c2[1] + z * np.dot(A['R'][k].mean(0), z))
    pts = np.asarray(pts)
    npts = len(pts)
    steps = [k for k in range(m) if A.get('par') and A['par'][k] == 'step']
    for k in steps:                                      # the two rings of a step: one point, two sizes
        i, j = seg[k]
        pts[i] = pts[j] = (pts[i] + pts[j]) / 2.0
    c0 = pts.mean(0)
    axes = np.linalg.svd(pts - c0)[2]
    off_line = np.linalg.norm((pts - c0) - np.outer((pts - c0) @ axes[0], axes[0]), axis=1).max()
    if npts >= 3 and not closed and off_line <= LINE_TOL:
        # points on one straight line within the source's precision: a straight axis (a bolt, a stud)
        pts = c0 + np.outer((pts - c0) @ axes[0], axes[0])
    elif closed and np.abs((pts - c0) @ axes[2]).max() <= PLANE_TOL:
        # a closed path that is planar within the source's precision is put on its plane: carried around a planar
        # loop the section comes back to itself exactly, so the closing joint is a true mitre like every other one
        pts = pts - np.outer((pts - c0) @ axes[2], axes[2])
    # joint planes: the rule where the source agrees with it, else the source's own plane
    dd = [None if k in steps else _unit(pts[(k + 1) % npts] - pts[k]) for k in range(m)]
    for k in steps:
        dd[k] = next((dd[q] for q in range(k - 1, -1, -1) if dd[q] is not None), None)
        if dd[k] is None:
            dd[k] = next(dd[q] for q in range(k + 1, m) if dd[q] is not None)
    normals = []
    for k in range(npts):
        din = dd[k - 1] if (closed or k > 0) else None
        dout = dd[k] if (closed or k < npts - 1) else None
        rule = dout if din is None else din if dout is None else _unit(din + dout)
        n = rn[k]
        # a rule holds when the source ring lies on the rule's plane through the point (the same test as for the ring
        # being planar at all): then the rule is written, not the measured normal
        on = lambda v: v is not None and float(np.abs((A['R'][k] - pts[k]) @ v).max()) <= PLANE_TOL
        if on(rule):
            normals.append(None)
        elif mode == 'joint' and din is not None and dout is not None and on(din):
            normals.append('in')
        elif mode == 'joint' and din is not None and dout is not None and on(dout):
            normals.append('out')
        else:
            normals.append([round(float(c), 9) for c in n])
    r6 = lambda v: [round(float(c), 6) for c in v]
    outline = None
    prof = None
    if ng:
        ng = recover.regular_polygon(loops[0], loops[1:])
        prof = dict(kind='NGON', **ng)
    else:
        seg2 = lambda p: [{'t': 'L', 'p': [[round(float(x), 6), round(float(y), 6)] for x, y in p] + [[round(float(p[0][0]), 6), round(float(p[0][1]), 6)]]}]
        outline = {'outer': seg2(loops[0]), 'inner': [seg2(h) for h in loops[1:]]}
    path = {'points': [r6(p) for p in pts], 'closed': bool(closed), 'section': mode}
    if any(v is not None for v in normals):
        path['normals'] = normals
    if A.get('scales'):
        path['scales'] = [round(float(f), 9) for f in A['scales']]
    zf = A['secn'][0] if mode == 'perpendicular' else rn[0]
    cand = dict(profile=prof, outline=outline, o=r6(pts[0]), x=[float(c) for c in x0], z=[float(c) for c in zf],
                vec=r6(pts[1 % npts] - pts[0]), cuts=[], path=path)
    return cand, None


def straight_candidate(A):
    """one-segment tube (a straight prism) -> plain extrusion: profile x vector, oblique ends as plane cuts"""
    c, why = candidate(A)
    if c is None:
        return None, why
    p0, p1 = np.array(c['path']['points'][0]), np.array(c['path']['points'][1])
    dvec = p1 - p0
    L = np.linalg.norm(dvec)
    dn = dvec / L
    normals = c['path'].get('normals') or [None, None]
    sec = np.array(A['S'][0][0])
    reach = float(np.linalg.norm(sec, axis=1).max())
    o, vec, cuts = p0.copy(), dvec.copy(), []
    for k, nn in enumerate(normals):
        if nn is None:
            continue
        n = np.array(nn, float)
        cosang = abs(np.dot(n, dn))
        e = reach * math.sqrt(max(0.0, 1 - cosang ** 2)) / cosang + 1.0
        if k == 0:
            o = o - dn * e
            keep = n if np.dot(n, dn) > 0 else -n
            pt = p0
        else:
            keep = -n if np.dot(n, dn) > 0 else n
            pt = p1
        vec = vec + dn * e
        cuts.append({'p': [round(float(x), 6) for x in pt], 'n': [float(x) for x in keep]})
    r6 = lambda v: [round(float(x), 6) for x in v]
    return dict(profile=c['profile'], outline=c['outline'], o=r6(o), x=c['x'], z=[float(x) for x in dn], vec=r6(vec), cuts=cuts), None


# ======================================================================================== rebuild and compare
def _vertices(shape):
    return np.array([tuple(v) for v in shape.vertices()], float) if shape.vertices() else np.zeros((0, 3))


def _nearest(A, B):
    """for every row of A the distance to the nearest row of B"""
    if not len(A) or not len(B):
        return np.array([np.inf])
    out = np.empty(len(A))
    for i in range(0, len(A), 256):
        D = np.linalg.norm(A[i:i + 256, None, :] - B[None, :, :], axis=2)
        out[i:i + 256] = D.min(1)
    return out


# ======================================================================================== entry point
def try_sweep(rec):
    """-> ([candidate per solid], 'ok') or (None, reason)"""
    import steelbuild
    import recover
    if sum(len(s['faces']) for s in rec['solids']) > MAX_FACES:
        return None, 'too many faces'
    srcs = steelbuild.exact_part(rec)
    if len(srcs) != len(rec['solids']) or not all(B.is_valid for B in srcs):
        return None, 'source solid not valid'
    cands, kinds, verts = [], [], []
    for so in rec['solids']:
        if so.get('voids'):
            return None, 'voids'
        V, rings, closed, why = find_tube(so['faces'])
        if rings is None:
            return None, why
        A, why = analyse(V, rings, closed)
        if A is None:
            return None, why
        if A['m'] == 1 and not closed and not A.get('scales'):
            c, why = straight_candidate(A)
            kinds.append('straight')
        else:
            c, why = candidate(A)
            kinds.append('%s %d segments%s%s' % (A['mode'], A['m'], ' closed' if closed else '', ' scaled' if A.get('scales') else ''))
        if c is None:
            return None, why
        cands.append(c)
        verts.append(V)
    # rebuild exactly as the client does (schedule rows -> steelbuild.build_part) and compare solid by solid
    pid = rec['part_id']
    try:
        built = recover.build_candidates(pid, cands)
    except Exception as e:
        if recover.is_oom(e):
            raise
        return None, 'rebuild failed (%s)' % type(e).__name__
    if len(built) != len(srcs):
        return None, 'rebuild gave %d solids' % len(built)
    for c, B, P, V, kind in zip(cands, srcs, built, verts, kinds):
        VP = _vertices(P)
        dv = max(_nearest(V, VP).max(), _nearest(VP, V).max())
        if dv > VTOL:
            return None, 'rebuilt sweep differs (vertices differ %.3f mm)' % dv
        ok, chk = recover.coincide(B, P)
        if not ok:
            return None, 'rebuilt sweep differs (%s)' % chk['reason']
        chk.update(kind=kind, vertex_mm=float(dv))
        c['check'] = chk
    return cands, 'ok'
