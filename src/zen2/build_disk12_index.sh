#!/bin/bash
# Build a compact lookup of every content hash Disk-1/Disk-2 already stored: sorted unique uint64 (first 8 bytes of sha256)
set -e
B=s3://annotationprod/cad-disk-extract
mkdir -p /work/idx && cd /work/idx
[ -s union.sqlite ] || /usr/local/bin/s5cmd --numworkers 16 cp --concurrency 32 --part-size 128 "$B/_state/dedup-union/union.sqlite" union.sqlite
python3 - <<'PY'
import sqlite3, array, json, time
t=time.time(); c=sqlite3.connect('/work/idx/union.sqlite')
stats=c.execute("SELECT disk, kind, COUNT(*) FROM digests GROUP BY disk, kind").fetchall()
print('digest rows by disk/kind:', stats)
a=array.array('Q')
for (d,) in c.execute("SELECT DISTINCT digest FROM digests WHERE kind='sha'"):
    if isinstance(d,(bytes,bytearray)) and len(d)>=8: a.append(int.from_bytes(d[:8],'big'))
a=array.array('Q', sorted(set(a)))
open('/work/idx/disk12_sha64.bin','wb').write(a.tobytes())
json.dump({'rows_by_disk_kind':stats,'distinct_sha64':len(a),'built':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())},open('/work/idx/disk12_sha64.json','w'))
print('distinct sha64', len(a), 'in', round(time.time()-t), 's')
PY
aws s3 cp --quiet /work/idx/disk12_sha64.bin $B/zentitude-data-4/_control/disk12_sha64.bin
aws s3 cp --quiet /work/idx/disk12_sha64.json $B/zentitude-data-4/_control/disk12_sha64.json
echo "index uploaded"
