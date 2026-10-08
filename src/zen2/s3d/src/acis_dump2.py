import sys
from common import *
import acis
import ezdxf.acis.sab as S
c = connect(MDB)
if sys.argv[1] == 'member':
    cols, rows = query(c, "SELECT TOP 1 CAST(g.oid AS char(36)), g.blob, g.xmin, g.ymin, g.zmin, g.xmax, g.ymax, g.zmax FROM (SELECT TOP 5 b.oid FROM dbo.COREBaseClass b WITH (INDEX(COREBaseClassClassIdIndex)) WHERE b.ClassId = 240007 ORDER BY b.oid) x JOIN dbo.GEOTOPSolidBody g ON g.oid = x.oid")
else:
    cols, rows = query(c, "SELECT CAST(g.oid AS char(36)), g.blob, g.xmin, g.ymin, g.zmin, g.xmax, g.ymax, g.zmax FROM dbo.GEOTOPSolidBody g WHERE g.oid='%s'" % sys.argv[1])
oid, blob = rows[0][0], rows[0][1]
print('oid', oid, 'bbox', rows[0][2:])
sab = acis.blob_to_sab(blob)
b = S.parse_sab(sab)
idx = {id(e): i for i, e in enumerate(b.entities)}
seen = {}
for i, e in enumerate(b.entities):
    if 'attrib' in e.name or seen.get(e.name, 0) >= int(sys.argv[2] if len(sys.argv) > 2 else 1):
        continue
    seen[e.name] = seen.get(e.name, 0) + 1
    toks = []
    for t in e.data:
        v = t.value
        if t.tag == S.Tags.POINTER:
            v = '->%s#%s' % (getattr(v, 'name', '?'), idx.get(id(v), '-'))
        elif isinstance(v, float):
            v = round(v, 4)
        elif isinstance(v, (list, tuple)):
            v = tuple(round(x, 4) for x in v)
        toks.append('%x:%s' % (t.tag, v))
    print(('#%d %s | %s' % (i, e.name, ' '.join(toks)))[:int(sys.argv[3]) if len(sys.argv) > 3 else 300])
