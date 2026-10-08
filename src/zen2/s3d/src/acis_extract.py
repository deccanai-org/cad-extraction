"""Decode ACIS solids for structural members (linear + curved) and slabs -> per-area geometry files (read-only SQL).

acis_extract.py plan            -> WORK/acis/plan.pkl  (object oid -> geometry oid, area, kind)
acis_extract.py run [--workers 8] -> WORK/acis/areas/<area>/<page>.pkl  ({oid: {'v','f','complete','flags'}})
acis_extract.py summary         -> WORK/acis_summary.json
"""
import os, sys, json, gzip, glob, time, pickle, collections, argparse, traceback
import numpy as np
from common import *

AD = os.path.join(WORK, 'acis')
STRUCT_RESULT = None


def plan():
    c = connect(MDB)
    g = {r[0]: r[1] for r in query(c, "SELECT RelationName, CAST(RelationGUID AS char(36)) FROM [MLNG@1_CDB_SCHEMA].dbo.RelationInfoView WHERE RelationName IN ('StructResult','StructEntityGeometry')")[1]}
    log('relations %s' % g)
    cols, rows = query(c, """
SELECT CAST(x.oidTarget AS char(36)) obj, CAST(r.oidTarget AS char(36)) geo
FROM dbo.CORERelationOrigin x WITH (INDEX(CORERelationOriginTypeIndex))
JOIN dbo.CORERelationOrigin r ON r.oid = x.oid AND r.RelationType = '%s'
WHERE x.RelationType = '%s'""" % (g['StructResult'], R['MemberToXS']))
    m2g = {o.upper(): gg.upper() for o, gg in rows}
    cols, rows = query(c, """
SELECT CAST(s.oid AS char(36)) obj, CAST(r.oidTarget AS char(36)) geo FROM dbo.STRUCTSPSSlabEntity s
JOIN dbo.CORERelationOrigin r ON r.oid = s.oid AND r.RelationType = '%s'""" % g['StructEntityGeometry'])
    s2g = {o.upper(): gg.upper() for o, gg in rows}
    items = []
    for f in glob.glob(os.path.join(OUT, 'json', 'structure', '*.jsonl.gz')):
        for line in gzip.open(f, 'rt'):
            r = json.loads(line)
            geo = (s2g if r['kind'] == 'slab' else m2g).get(r['oid'])
            if geo:
                items.append((r['oid'], geo, r['area'], r['kind']))
    os.makedirs(AD, exist_ok=True)
    pickle.dump(items, open(os.path.join(AD, 'plan.pkl'), 'wb'))
    log('acis plan: %d objects with a solid (members %d, slabs %d); mapping m2g %d s2g %d' % (
        len(items), sum(1 for i in items if i[3] != 'slab'), sum(1 for i in items if i[3] == 'slab'), len(m2g), len(s2g)))


def encode(faces):
    """faces [(outer, holes)] -> compact dict: vertex array (float64, rounded 1e-6 m) + faces as index lists"""
    idx = {}; V = []
    def vi(p):
        k = (round(float(p[0]), 6), round(float(p[1]), 6), round(float(p[2]), 6))
        i = idx.get(k)
        if i is None:
            i = idx[k] = len(V); V.append(k)
        return i
    F = []
    for o, hs in faces:
        lo = [vi(p) for p in o]
        lo = [a for j, a in enumerate(lo) if a != lo[j - 1]] if len(lo) > 1 else lo
        if len(set(lo)) < 3:
            continue
        hh = []
        for h in hs:
            lh = [vi(p) for p in h]
            if len(set(lh)) >= 3:
                hh.append(lh)
        F.append((lo, hh))
    return np.array(V, float), F


_c = None


def _page(job):
    global _c
    import acis_geom
    if _c is None:
        _c = connect(MDB)
    pid, items = job
    by_area = collections.defaultdict(dict); st = collections.Counter()
    geo2 = {g: (o, a, k) for o, g, a, k in items}
    gl = list(geo2)
    for i in range(0, len(gl), 400):
        cols, rows = query(_c, "SELECT CAST(oid AS char(36)), blob FROM dbo.GEOTOPSolidBody WHERE oid IN (%s)" % guid_list(gl[i:i + 400]))
        for gid, blob in rows:
            o, a, k = geo2[gid.upper()]
            try:
                faces, complete, flags = acis_geom.body_faces(blob)
                V, F = encode(faces)
                if len(F) == 0:
                    st[k + '_empty'] += 1; continue
                by_area[a][o] = {'v': V, 'f': F, 'complete': bool(complete), 'flags': flags, 'kind': k}
                st[k + ('_complete' if complete else '_partial')] += 1
                for fl in flags:
                    st['flag_' + fl.split(':')[0]] += 1
            except Exception as e:
                st[k + '_error'] += 1
                st['err_' + type(e).__name__] += 1
    for a, d in by_area.items():
        od = os.path.join(AD, 'areas', safe_name(a.replace('/', '__'), 90))
        os.makedirs(od, exist_ok=True)
        with open(os.path.join(od, '%s.pkl.tmp' % pid), 'wb') as f:
            pickle.dump(d, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(os.path.join(od, '%s.pkl.tmp' % pid), os.path.join(od, '%s.pkl' % pid))
    open(os.path.join(AD, 'done', pid), 'w').write(json.dumps(st))
    return pid, dict(st)


def run(workers):
    items = pickle.load(open(os.path.join(AD, 'plan.pkl'), 'rb'))
    items.sort(key=lambda x: x[1])
    pages = [('p%05d' % (i // 4000), items[i:i + 4000]) for i in range(0, len(items), 4000)]
    os.makedirs(os.path.join(AD, 'done'), exist_ok=True)
    todo = [p for p in pages if not os.path.exists(os.path.join(AD, 'done', p[0]))]
    log('acis pages %d todo %d' % (len(pages), len(todo)))
    import multiprocessing as mp
    tot = collections.Counter(); n = 0
    with mp.get_context('fork').Pool(workers, maxtasksperchild=40) as pool:
        for pid, st in pool.imap_unordered(_page, todo):
            tot.update(st); n += 1
            if n % 10 == 0:
                log('%d/%d %s' % (n, len(todo), dict(tot)))
    summary()


def summary():
    tot = collections.Counter()
    for f in glob.glob(os.path.join(AD, 'done', '*')):
        tot.update(json.load(open(f)))
    s = {'generated': utcnow(), 'counts': dict(tot),
         'method': 'GEOTOPSolidBody blob -> Deflate64 -> OLE2 JS_TOPOLOGY_STREAM -> ACIS SAB R26 (S3D name interning + extra field handled) -> '
                   'B-rep walk: planar faces exact (straight edges exact, circles sampled <=4 mm sagitta, B-spline edges de Boor-sampled), '
                   'cylinder/cone walls triangulated, spline faces boundary-filled (approx) or skipped'}
    json.dump(s, open(os.path.join(WORK, 'acis_summary.json'), 'w'), indent=1)
    log('acis summary %s' % json.dumps(s['counts']))


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('cmd'); ap.add_argument('--workers', type=int, default=8); a = ap.parse_args()
    {'plan': plan, 'run': lambda: run(a.workers), 'summary': summary}[a.cmd]()
