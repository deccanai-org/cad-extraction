import sys, time, collections, json
import numpy as np
from common import *
import acis_geom

SQL = {
    'slab': """SELECT TOP %(N)d CAST(g.oid AS char(36)), g.blob, g.xmin, g.ymin, g.zmin, g.xmax, g.ymax, g.zmax FROM dbo.STRUCTSPSSlabEntity s
               JOIN dbo.CORERelationOrigin r ON r.oid = s.oid AND r.RelationType = (SELECT TOP 1 RelationGUID FROM [MLNG@1_CDB_SCHEMA].dbo.RelationInfoView WHERE RelationName='StructEntityGeometry')
               JOIN dbo.GEOTOPSolidBody g ON g.oid = r.oidTarget ORDER BY NEWID()""",
    'member': """SELECT CAST(g.oid AS char(36)), g.blob, g.xmin, g.ymin, g.zmin, g.xmax, g.ymax, g.zmax FROM (SELECT TOP %(N)d b.oid FROM dbo.COREBaseClass b WITH (INDEX(COREBaseClassClassIdIndex))
               WHERE b.ClassId = 240007 AND b.oid > '%(START)s' ORDER BY b.oid) x JOIN dbo.GEOTOPSolidBody g ON g.oid = x.oid""",
}


def main(kind, n, start='00000000-0000-0000-0000-000000000000'):
    c = connect(MDB)
    cols, rows = query(c, SQL[kind] % {'N': n, 'START': start})
    flags = collections.Counter(); errs = collections.Counter(); dev = []; comp = 0; t0 = time.time(); nf = []
    bad = []
    for oid, blob, *bb in rows:
        try:
            faces, complete, fl = acis_geom.body_faces(blob)
        except Exception as e:
            errs['%s:%s' % (type(e).__name__, str(e)[:60])] += 1; continue
        flags.update(fl); comp += complete; nf.append(len(faces))
        V = np.array([p for o, hs in faces for p in o + [q for h in hs for q in h]])
        if len(V) and bb[0] is not None:
            d = float(np.abs(np.concatenate([V.min(0), V.max(0)]) - np.array(bb, float)).max())
            dev.append(d)
            if d > 0.01 and len(bad) < 5:
                bad.append((oid, round(d, 4), fl))
    dt = time.time() - t0
    dev = np.array(dev)
    print(json.dumps({'kind': kind, 'bodies': len(rows), 'errors': dict(errs), 'complete': comp, 'faces_mean': float(np.mean(nf)) if nf else 0,
                      'ms_per_body': round(1000 * dt / max(1, len(rows)), 1), 'flags': dict(flags),
                      'bbox_dev_p50_mm': round(1000 * float(np.percentile(dev, 50)), 2) if len(dev) else None,
                      'bbox_dev_p99_mm': round(1000 * float(np.percentile(dev, 99)), 2) if len(dev) else None,
                      'within_2mm_pct': round(100 * float((dev < 0.002).mean()), 2) if len(dev) else None, 'bad_samples': bad}, indent=0))


if __name__ == '__main__':
    main(sys.argv[1], int(sys.argv[2]), *(sys.argv[3:4]))
