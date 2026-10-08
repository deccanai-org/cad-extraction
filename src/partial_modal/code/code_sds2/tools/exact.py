#!/usr/bin/env python3
"""exact_geometry.jsonl for parts whose source has no parameters (faceted surfaces): their polygon faces.

The faces come from the source IFC at full precision: exact_ifc.jsonl, written by extract.py from the IFC's own
IfcFacetedBrep[WithVoids] / IfcShellBasedSurfaceModel / IfcFaceBasedSurfaceModel / IfcPolygonalFaceSet /
IfcTriangulatedFaceSet items, through mapped items, placements and the file's length unit. Such a record is used when
  - it is the delivered part at full precision: every vertex of either lies within the delivered STEP's 0.01 mm
    coordinate grid of a vertex of the other (GRID_VERTEX_MM; this bounds the bounding boxes the same way) and both
    state the same volume within 1 % (the delivered model may hold the closed bodies of one faceted IFC solid as
    separate solids); a part the delivered model lacks is not compared, and
  - its faces build, as steelbuild builds an exact part, into the valid solids they state (exact_check.py, OpenCASCADE
    in its own process).
Every other exact part (faceted surfaces with openings subtracted, geometry that is not faceted in the IFC, shells that
do not close, any disagreement with the delivered model) takes its faces from the delivered STEP, as before. Where the
faces of every exact part came from is recorded in its record's 'source' and in exact_sources.csv (one row per exact
part: faces_source = ifc | delivered_step | none, and why not ifc) - recover.py later rebuilds most of these parts
parametrically from those faces, and the file still says which faces they were recovered from. Without exact_ifc.jsonl
(schedules extracted by an older extract.py) every part takes the delivered faces, exactly as before.

usage: exact.py SCHEDULE_DIR DELIVERED.step"""
import csv, json, os, shutil, subprocess, sys, tempfile
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stepfacets

SRC_IFC = 'IFC faceted geometry, full precision'
SRC_DELIVERED = 'faceted B-rep (IFC) as delivered'          # the delivered STEP's faces (0.01 mm coordinate grid)
# rounding a coordinate to the delivered 0.01 mm grid moves a vertex by at most 0.005 * sqrt(3) = 0.00866 mm (also in
# the rotated frame of a mapped item)
GRID_VERTEX_MM = 0.009
DELIVERED_VOL_REL = 0.01


def _verts(solids, key):
    pts = [p for s in solids for sh in [s[key]] + list(s.get('voids', [])) for fc in sh for lp in fc for p in lp]
    return np.asarray(pts, float).reshape(-1, 3)


def _near_all(A, B, tol):
    """every point of A within tol of some point of B (k-d tree; without scipy: grid hashing, cell = tol)"""
    try:
        from scipy.spatial import cKDTree
    except ImportError:
        cKDTree = None
    if cKDTree is not None:
        d, _ = cKDTree(B).query(A, k=1, distance_upper_bound=tol * 1.0000001)
        return bool(np.all(d <= tol))
    cell = {}
    kb = np.floor(B / tol).astype(np.int64)
    for i, k in enumerate(map(tuple, kb)):
        cell.setdefault(k, []).append(i)
    ka = np.floor(A / tol).astype(np.int64)
    off = [(i, j, k) for i in (-1, 0, 1) for j in (-1, 0, 1) for k in (-1, 0, 1)]
    for p, k in zip(A, map(tuple, ka)):
        ok = False
        for o in off:
            for i in cell.get((k[0] + o[0], k[1] + o[1], k[2] + o[2]), ()):
                if np.linalg.norm(B[i] - p) <= tol:
                    ok = True
                    break
            if ok:
                break
        if not ok:
            return False
    return True


def _as_mass(solids, key):
    return [{'outer': [[np.asarray(lp, float) for lp in fc] for fc in s[key]],
             'voids': [[[np.asarray(lp, float) for lp in fc] for fc in v] for v in s.get('voids', [])]} for s in solids]


def disagreement(ifc_solids, delivered_solids):
    """'' when the IFC faces are the delivered part at full precision, otherwise what differs"""
    A, B = _verts(ifc_solids, 'faces'), _verts(delivered_solids, 'outer')
    if not len(A) or not len(B):
        return 'no vertices'
    # cheap pre-test, implied by the vertex test below
    if max(np.max(np.abs(A.min(0) - B.min(0))), np.max(np.abs(A.max(0) - B.max(0)))) > GRID_VERTEX_MM:
        return 'bounding box'
    if not (_near_all(A, B, GRID_VERTEX_MM) and _near_all(B, A, GRID_VERTEX_MM)):
        return 'vertices'
    vi = stepfacets.mass(_as_mass(ifc_solids, 'faces'))[0]
    vd = stepfacets.mass(_as_mass(delivered_solids, 'outer'))[0]
    if abs(vi - vd) > DELIVERED_VOL_REL * max(abs(vd), 1e-9):
        return 'volume'
    return ''


def build_check(recs, jobs=None):
    """{part_id: '' | reason}: exact_check.py (OpenCASCADE, in its own process) builds every record"""
    if not recs:
        return {}
    d = tempfile.mkdtemp(prefix='exact_check_')
    fi, fo = os.path.join(d, 'in.jsonl'), os.path.join(d, 'out.json')
    with open(fi, 'w') as fh:
        for r in recs:
            fh.write(json.dumps(r, separators=(',', ':')) + '\n')
    jobs = jobs or int(os.environ.get('EXACT_JOBS', 0)) or os.cpu_count() or 1
    try:
        subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'exact_check.py'), fi, fo,
                        '--jobs', str(jobs)], check=True, stdout=subprocess.DEVNULL)
        res = json.load(open(fo))
    except Exception as e:                  # no check, no IFC faces: every part keeps the delivered faces
        res = {r['part_id']: 'build check failed (%s)' % type(e).__name__ for r in recs}
    shutil.rmtree(d, ignore_errors=True)
    return res


def main(folder, step):
    parts = list(csv.DictReader(open(os.path.join(folder, 'parts.csv'))))
    want = {p['part_id'] for p in parts if p['geometry'] == 'exact'}
    ifc = {}
    fn = os.path.join(folder, 'exact_ifc.jsonl')
    if os.path.exists(fn):
        for line in open(fn):
            if line.strip():
                r = json.loads(line)
                if r['part_id'] in want:
                    ifc[r['part_id']] = r
    import occstep
    sds2 = occstep.sds2_mode(folder)
    if sds2:
        # IFC emitted from an SDS/2 conversion: the delivered STEP is the converter's exact B-rep (true cylindrical bolt
        # holes), not polygon faces on a grid, so there is no polygon comparison to make here; the IFC's faces stand
        # when they build, and verify.py holds every rebuilt part to the delivered B-rep (occstep.delivered_props)
        P = {}
        agree = {pid: '' for pid in ifc}
    else:
        P = stepfacets.Model(step).products()
    # the IFC faces of a part stand only if they are the delivered part at full precision ...
    if not sds2:
        agree = {pid: (disagreement(r['solids'], P[pid]['solids']) if pid in P else '') for pid, r in ifc.items()}
    # ... and build (as steelbuild builds an exact part) into the valid solids they state
    built = build_check([ifc[pid] for pid in sorted(ifc) if not agree[pid]])
    n, src = 0, {}
    with open(os.path.join(folder, 'exact_geometry.jsonl'), 'w') as fh:
        for pid in sorted(want):
            d = P.get(pid)
            why = 'not faceted in the IFC, or openings / shells that do not close (extract_info.json exact_faces)'
            if pid in ifc:
                why = ('delivered model differs: ' + agree[pid]) if agree[pid] else \
                      (('build: ' + built[pid]) if built.get(pid, 'not checked') else '')
                if not why:
                    fh.write(json.dumps({'part_id': pid, 'source': SRC_IFC, 'solids': ifc[pid]['solids']},
                                        separators=(',', ':')) + '\n')
                    src[pid] = ('ifc', '' if (d is not None or sds2) else 'no delivered part to compare with')
                    n += 1
                    continue
            if d is None:
                src[pid] = ('none', why + '; no delivered part')
                continue
            r = lambda lp: [[round(float(v), 6) for v in p] for p in lp]
            solids = [{'faces': [[r(lp) for lp in fc] for fc in s['outer']], 'voids': [[[r(lp) for lp in fc] for fc in vd] for vd in s.get('voids', [])]}
                      for s in d['solids']]
            fh.write(json.dumps({'part_id': pid, 'source': SRC_DELIVERED, 'solids': solids}, separators=(',', ':')) + '\n')
            src[pid] = ('delivered_step', why)
            n += 1
    with open(os.path.join(folder, 'exact_sources.csv'), 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['part_id', 'faces_source', 'why_not_ifc'])
        for pid in sorted(src):
            w.writerow([pid, src[pid][0], src[pid][1]])
    cnt = {k: sum(1 for v in src.values() if v[0] == k) for k in ('ifc', 'delivered_step', 'none')}
    fi = os.path.join(folder, 'extract_info.json')
    if os.path.exists(fi):                  # the counts beside extract.py's own (exact_faces)
        info = json.load(open(fi))
        info.setdefault('exact_faces', {})['faces_source'] = cnt
        json.dump(info, open(fi, 'w'), indent=1)
    print('exact parts written', n, 'of', len(want), 'faces from', json.dumps(cnt))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
