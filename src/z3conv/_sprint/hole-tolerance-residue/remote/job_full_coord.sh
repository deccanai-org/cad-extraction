#!/bin/bash
# coordinator overflow box: production-path proof (convert_one -> ifc2step6 -> step_check) on deployed code j: kit_jg (j + catalog guard) vs kit_jp (j + patch)
S=hole-tolerance-residue; W=/work/agentwork/$S; cd $W
export AWS_DEFAULT_REGION=ap-south-1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/$S
mkdir -p kit_j db1
aws s3 sync --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/db1/ kit_j/ --exclude '*' --include '*.py' --include '*.json' --include '*.sh' --exclude '*/*'
grep -n "^CODE" kit_j/worker.py; md5sum kit_j/db1bolts.py kit_j/db1step.py
bash kit_j/setup.sh $W/conv > setup.log 2>&1; tail -3 setup.log
rm -rf kit_jg kit_jp; cp -a kit_j kit_jg; cp -a kit_j kit_jp
cp fix/db1bolts_guardonly.py kit_jg/db1bolts.py; cp fix/db1bolts.py fix/db1step.py kit_jp/
md5sum kit_jg/db1bolts.py kit_jp/db1bolts.py kit_jp/db1step.py
python3 - <<'PY'
import json, subprocess
M = {m['id'][:12]: m for m in json.load(open('models2.json'))}
for i in ('4671ea562003', 'a0a1b3769d87', '7c68f0c9874e', '291547d3c10f', '5a2284473e4e'):
    m = M[i]; subprocess.run(['aws', 's3', 'cp', '--quiet', f"s3://bim-proprietary-data/{m['input_key']}", f"db1/{m['id']}.db1"])
PY
ls -la db1
export HTR_PY84=$W/conv/ifc84/bin/python HTR_PY=$W/conv/env/bin/python
for k in kit_jg kit_jp; do for i in 4671ea562003 a0a1b3769d87 7c68f0c9874e 5a2284473e4e 291547d3c10f; do echo "$k $i"; done; done | \
  xargs -P 5 -n 2 sh -c '$HTR_PY fullpath.py "$0" "$1" >> full_coord.log 2>&1'
aws s3 cp --quiet full_coord.log $OUT/full_coord.log
echo FULLDONE >> full_coord.log; aws s3 cp --quiet full_coord.log $OUT/full_coord.log
