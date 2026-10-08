#!/bin/bash
# code p test: decoder + IFC writer only, code o kit (live) vs code p (test prefix), old-engine models
set -u
T=/opt/conv/scratch_cutr; mkdir -p $T/r $T/src; cd $T
aws s3 sync --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/test/db1r/ $T/r/
rm -rf $T/o; cp -a /opt/conv/kit/db1 $T/o
PY84=/opt/conv/ifc84/bin/python
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
while read ID K; do
  [ -n "$K" ] || continue
  [ -s src/$ID.db1 ] || aws s3 cp --quiet "s3://bim-proprietary-data/$K" src/$ID.db1
  ENG=$($PY84 -c "
import re,zlib
raw=open('src/$ID.db1','rb').read(1<<16)
d=zlib.decompressobj(16+zlib.MAX_WBITS).decompress(raw) if raw[:2]==b'\x1f\x8b' else raw
m=re.search(rb'(\d+\.\d+)',d[:16]); print(m.group(1).decode() if m else 'none')")
  for V in o r; do
    O=$T/out/$ID/$V; mkdir -p $O
    $PY84 -c "import json; L=json.load(open('$T/$V/layouts.json')); e=L.get('$ENG') or {}; json.dump(e.get('layout'), open('$O/layout.json','w')); json.dump([v['layout'] for v in L.values() if v.get('layout')], open('$O/variants.json','w'))"
    ( cd $T/$V && nice -n 10 timeout 1800 systemd-run --scope --quiet -p MemoryMax=24G $PY84 $T/$V/convert_one.py $T/src/$ID.db1 $O/model.ifc $T/$V/tekla_profiles.json $O/layout.json $O/convert.json $O/variants.json > $O/log.txt 2>&1; echo "rc=$?" >> $O/log.txt ) &
  done
  wait
  echo "== $ID $ENG"
done <<LIST
e5e813f81462b868 Zenitude-data-3/Jobs & Data_Files_Completed_On_Server12/Jobs Files/FTP Data 19-3-2014/FTP Data 21-3-2014-10.10.40.4/FTP6/kwik/UPLOADS FROM MOLDTEK/JANUARY2012/Submittals_27.01.2012/1620-D-110/MODEL/1620-D-110/1620-D-110.db1
63ecb8207e981b6d cad-disk-extract/Disk-2/Jobs_Data_Files_Completed_On_Server12_Jobs_Files_FTP_Data_19-3-2014_FTP_Data_21-3-2014-10.10.40.4_FTP6_kwik_UPLOADS_FROM_MOLDTEK_MAR_2012_1620-D-110_DT-09.03.2012.zip-05d0840dd9f7/1620-D-110_DT-09.03.2012/MODEL/1620-D-110/1620-D-110.db1
8ebd3570ad53a76f Zenitude-data-3/Jobs & Data_Files_Completed_On_Server12/Jobs Files/FTP Data 19-3-2014/FTP Data 21-3-2014-10.10.40.4/FTP6/kwik/UPLOADS FROM MOLDTEK/NOVEMBER-2011/1220-C-003 21.11.2011/MODEL/1220-C-003/KWISS.db1
LIST
