#!/bin/bash
# overflow box: census + production path with the updated patch (kit_jp4 = code j + db1bolts patch + db1step patch incl. bolt-inside-part skip)
S=hole-tolerance-residue; W=/work/agentwork/$S; cd $W
export AWS_DEFAULT_REGION=ap-south-1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export HTR_PY=$W/conv/env/bin/python HTR_PY84=$W/conv/ifc84/bin/python HTR_ASC=1
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/$S
rm -rf kit_jp4; cp -a kit_j kit_jp4; cp fix/db1bolts.py fix/db1step.py kit_jp4/; md5sum kit_jp4/db1bolts.py kit_jp4/db1step.py
for k in kit_jp4; do for i in 291547d3c10f a7f94f2edc0f 4671ea562003 a0a1b3769d87 7c68f0c9874e 5a2284473e4e; do echo "$k $i"; done; done > fp.list
( [ -f db1/$(python3 -c "import json;print([m['id'] for m in json.load(open('models2.json')) if m['id'].startswith('a7f94f2edc0f')][0])").db1 ] || true )
$HTR_PY runjob2.py models2.json kit_jp4 census 14 > census_v4.log 2>&1 &
CP=$!
true
cat fp.list | xargs -P 2 -n 2 sh -c '$HTR_PY fullpath.py "$0" "$1" >> full_v4.log 2>&1'
wait $CP
aws s3 cp --quiet census_v4.log $OUT/census_v4.log; aws s3 cp --quiet full_v4.log $OUT/full_v4.log
echo V4DONE >> full_v4.log; aws s3 cp --quiet full_v4.log $OUT/full_v4.log
