#!/usr/bin/env python3
"""Rebuilt-part extents for tekla_checks.py (build123d / OpenCASCADE only - never imports ifcopenshell).

For every part of a schedule folder it rebuilds the part with steelbuild.build_part (exactly as verify.py does) and
measures, in millimetres:

  frame_ext_x/y/z   extents of the rebuilt solid in the frame of its first body solid
                    (x = profile x axis, z = profile normal = extrusion axis of a member, y = z cross x)
  face_ext_a/b/c    extents in the frame of the part's largest planar face (z = face normal, x = its longest straight
                    edge), sorted descending - orientation-free, also for parts built from exact faces (no body frame)
  plane_t/a/b       extent along the normal of the largest planar face (a plate's thickness) and the in-plane sides of
                    the minimum-area rectangle aligned with an edge of the projected convex hull
  plane_cands       in-plane sides for every hull-edge direction (JSON, longest edges first, at most 120)
  lo_*/hi_*         world axis-aligned bounding box (optimal)
  volume            volume of the rebuilt solids (cross-check against verification.csv)

usage: extents_worker.py SCHED_DIR OUT.csv [--jobs N] [--kit DIR]
"""
import argparse, csv, json, math, os, sys, time
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool

KIT_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'pm', 'kit')
_S = None


def _init(folder, kit):
    global _S
    sys.path.insert(0, kit)
    import steelbuild
    _S = steelbuild.Schedules(folder)


def _num(v):
    return float(v) if v not in (None, '') else 0.0


def _hull2d(p):
    """convex hull (monotone chain) of 2D points, counter-clockwise, as an (n, 2) array"""
    import numpy as np
    pts = sorted(set((round(float(x), 6), round(float(y), 6)) for x, y in p))
    if len(pts) <= 2:
        return np.array(pts, float)
    cross = lambda o, a, b: (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for q in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], q) <= 0:
            lower.pop()
        lower.append(q)
    for q in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], q) <= 0:
            upper.pop()
        upper.append(q)
    return np.array(lower[:-1] + upper[:-1], float)


def _one(part):
    import steelbuild
    import numpy as np
    from build123d import Compound, Plane, Vector
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    pid = part['part_id']
    row = dict(part_id=pid)
    t0 = time.time()
    try:
        solids = steelbuild.build_part(part, _S)
        if not solids:
            row['ext_status'] = 'no_solids'
            return row
        comp = Compound(solids) if len(solids) > 1 else solids[0]
        vol = 0.0
        for s in solids:
            g = GProp_GProps()
            BRepGProp.VolumeProperties_s(s.wrapped, g)
            vol += g.Mass()
        row['volume'] = round(vol, 3)
        bb = comp.bounding_box(optimal=True)
        row.update(lo_x=round(bb.min.X, 4), lo_y=round(bb.min.Y, 4), lo_z=round(bb.min.Z, 4),
                   hi_x=round(bb.max.X, 4), hi_y=round(bb.max.Y, 4), hi_z=round(bb.max.Z, 4))
        body = _S.body_of.get(pid, [])
        if body and part.get('geometry') != 'exact':
            s0 = _S.solids[body[0]]
            o = Vector(_num(s0['ox']), _num(s0['oy']), _num(s0['oz']))
            x = Vector(_num(s0['xx']), _num(s0['xy']), _num(s0['xz']))
            z = Vector(_num(s0['zx']), _num(s0['zy']), _num(s0['zz']))
            pl = Plane(origin=o, x_dir=x, z_dir=z)
            loc = pl.to_local_coords(comp)
            lb = loc.bounding_box(optimal=True)
            row.update(frame_ext_x=round(lb.max.X - lb.min.X, 4), frame_ext_y=round(lb.max.Y - lb.min.Y, 4),
                       frame_ext_z=round(lb.max.Z - lb.min.Z, 4), frame_lo_z=round(lb.min.Z, 4),
                       frame_hi_z=round(lb.max.Z, 4))
            v = np.array([_num(s0['vx']), _num(s0['vy']), _num(s0['vz'])])
            row['extrusion_mm'] = round(float(np.linalg.norm(v)), 4)
            row['n_body'] = len(body)
        # orientation-free extents: frame of the largest planar face (z = its normal) and its longest straight edge
        # (x); for a plate that is the plate face + its longest side, for a member a web/flange face + the member axis
        from build123d import GeomType
        faces = [f for f in comp.faces() if f.geom_type == GeomType.PLANE]
        if faces:
            f0 = max(faces, key=lambda f: f.area)
            nrm = f0.normal_at()
            lines = [e for e in f0.edges() if e.geom_type == GeomType.LINE and e.length > 1e-6]
            if lines:
                e0 = max(lines, key=lambda e: e.length)
                xd = (e0 @ 1) - (e0 @ 0)
                xd = xd - nrm * xd.dot(nrm)
                if xd.length > 1e-9:
                    fp = Plane(origin=f0.center(), x_dir=xd, z_dir=nrm)
                    fb = fp.to_local_coords(comp).bounding_box(optimal=True)
                    sides = sorted([fb.max.X - fb.min.X, fb.max.Y - fb.min.Y, fb.max.Z - fb.min.Z], reverse=True)
                    row.update(face_ext_a=round(sides[0], 4), face_ext_b=round(sides[1], 4), face_ext_c=round(sides[2], 4))
            # in-plane extents in the plane of the largest planar face, for every direction of an edge of the convex
            # hull of the part projected on that plane: a plate's own coordinate system (in which an authoring tool
            # reports its length / height) is aligned with one of its edges, but which one is not exported
            n = np.array([nrm.X, nrm.Y, nrm.Z], float)
            n /= np.linalg.norm(n)
            pts = [(v.X, v.Y, v.Z) for v in comp.vertices()]
            for e in comp.edges():
                if e.geom_type != GeomType.LINE:
                    pts += [((e @ t).X, (e @ t).Y, (e @ t).Z) for t in np.linspace(0.0, 1.0, 17)]
            P = np.array(pts, float)
            u = np.cross(n, [1.0, 0.0, 0.0] if abs(n[0]) < 0.9 else [0.0, 1.0, 0.0])
            u /= np.linalg.norm(u)
            w = np.cross(n, u)
            hn = P @ n
            row['plane_t'] = round(float(hn.max() - hn.min()), 4)
            hull = _hull2d(np.stack([P @ u, P @ w], axis=1))
            cands, seen = [], set()
            per = sum(float(np.linalg.norm(hull[(i + 1) % len(hull)] - hull[i])) for i in range(len(hull)))
            for i in range(len(hull)):
                d = hull[(i + 1) % len(hull)] - hull[i]
                L = float(np.linalg.norm(d))
                if L < 1e-6 or L < 1e-4 * per:
                    continue
                d /= L
                key = round(math.atan2(d[1], d[0]) % math.pi, 4)
                if key in seen:
                    continue
                seen.add(key)
                a_ = hull @ d
                b_ = hull @ np.array([-d[1], d[0]])
                ea, eb = float(a_.max() - a_.min()), float(b_.max() - b_.min())
                cands.append((L, sorted([round(ea, 3), round(eb, 3)], reverse=True)))
            if cands:
                best = min(cands, key=lambda c: c[1][0] * c[1][1])[1]
                row.update(plane_a=best[0], plane_b=best[1])
                cands.sort(key=lambda c: -c[0])           # longest hull edges first
                row['plane_cands'] = json.dumps([c[1] for c in cands[:120]], separators=(',', ':'))
        row['ext_status'] = 'ok'
    except Exception as e:
        row['ext_status'] = 'error'
        row['ext_error'] = f'{type(e).__name__}: {e}'
    row['ext_seconds'] = round(time.time() - t0, 3)
    return row


COLS = ['part_id', 'ext_status', 'volume', 'n_body', 'extrusion_mm', 'frame_ext_x', 'frame_ext_y', 'frame_ext_z',
        'frame_lo_z', 'frame_hi_z', 'face_ext_a', 'face_ext_b', 'face_ext_c', 'plane_t', 'plane_a', 'plane_b', 'plane_cands', 'lo_x', 'lo_y', 'lo_z', 'hi_x', 'hi_y', 'hi_z',
        'ext_seconds', 'ext_error']


def run(parts, jobs, initargs):
    """a part that crashes its worker (native fault) is isolated by re-running smaller groups"""
    try:
        with ProcessPoolExecutor(min(jobs, max(1, len(parts))), initializer=_init, initargs=initargs) as ex:
            return list(ex.map(_one, parts, chunksize=8 if len(parts) > 256 else 1))
    except BrokenProcessPool:
        if len(parts) == 1:
            return [dict(part_id=parts[0]['part_id'], ext_status='crash')]
        n = max(1, len(parts) // 8)
        out = []
        for i in range(0, len(parts), n):
            out += run(parts[i:i + n], jobs, initargs)
        return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('folder')
    ap.add_argument('out')
    ap.add_argument('--jobs', type=int, default=4)
    ap.add_argument('--kit', default=KIT_DEFAULT)
    ap.add_argument('--parts', default='', help='comma-separated part ids (default: all)')
    a = ap.parse_args()
    kit = os.path.abspath(a.kit)
    parts = list(csv.DictReader(open(os.path.join(a.folder, 'parts.csv'), newline='', encoding='utf-8')))
    if a.parts:
        want = set(a.parts.split(','))
        parts = [p for p in parts if p['part_id'] in want]
    t0 = time.time()
    rows = run(parts, a.jobs, (a.folder, kit))
    tmp = a.out + '.tmp'
    with open(tmp, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow(r)
    os.replace(tmp, a.out)
    print(f'{len(rows)} parts, {time.time() - t0:.1f}s -> {a.out}')


if __name__ == '__main__':
    main()
