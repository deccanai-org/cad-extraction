"""Survey GEOTOPSolidBody blobs: entity/surface/curve types for slab, member and design-solid bodies (read-only)."""
import sys, collections, json
from common import *
import acis
import ezdxf.acis.sab as S

KIND_SQL = {
    'slab': """SELECT TOP %(N)d CAST(g.oid AS char(36)) oid, g.blob FROM dbo.STRUCTSPSSlabEntity s
               JOIN dbo.CORERelationOrigin r ON r.oid = s.oid AND r.RelationType = (SELECT TOP 1 RelationGUID FROM [MLNG@1_CDB_SCHEMA].dbo.RelationInfoView WHERE RelationName='StructEntityGeometry')
               JOIN dbo.GEOTOPSolidBody g ON g.oid = r.oidTarget ORDER BY NEWID()""",
    'member': """SELECT CAST(g.oid AS char(36)) oid, g.blob FROM (SELECT TOP %(N)d b.oid FROM dbo.COREBaseClass b WITH (INDEX(COREBaseClassClassIdIndex))
               WHERE b.ClassId = 240007 ORDER BY b.oid) x JOIN dbo.GEOTOPSolidBody g ON g.oid = x.oid""",
}


def survey(kind, n):
    c = connect(MDB)
    cols, rows = query(c, KIND_SQL[kind] % {'N': n})
    ent = collections.Counter(); per_body = []
    fails = collections.Counter()
    for oid, blob in rows:
        try:
            sab = acis.blob_to_sab(blob)
            b = S.parse_sab(sab)
            names = collections.Counter(e.name for e in b.entities)
            ent.update(names)
            surf = {k for k in names if k.endswith('-surface')}
            curv = {k for k in names if k.endswith('-curve')}
            per_body.append((tuple(sorted(surf)), tuple(sorted(curv))))
        except Exception as e:
            fails[type(e).__name__ + ':' + str(e)[:60]] += 1
    combos = collections.Counter(per_body)
    print('==', kind, 'bodies', len(rows), 'fails', dict(fails))
    print(' entity types', [(k, v) for k, v in ent.most_common(30)])
    print(' surface/curve combos', combos.most_common(10))


if __name__ == '__main__':
    survey(sys.argv[1], int(sys.argv[2]))
