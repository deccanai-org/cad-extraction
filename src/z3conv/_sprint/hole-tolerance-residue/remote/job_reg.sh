#!/bin/bash
# BOX-B: regression of the hole-tolerance patch. kit_i = deployed code i; kit_g = code i + catalog crash guard only; kit_p = full patch
S=hole-tolerance-residue; W=/work/agentwork/$S; cd $W
export AWS_DEFAULT_REGION=ap-south-1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/$S
rm -rf kit_g kit_p; cp -a kit_i kit_g; cp -a kit_i kit_p
cp fix/db1bolts_guardonly.py kit_g/db1bolts.py
cp fix/db1bolts.py fix/db1step.py kit_p/
md5sum kit_*/db1bolts.py kit_*/db1step.py
/opt/conv/env/bin/python runjob.py models2.json kit_i,kit_g,kit_p census 16 > reg.log 2>&1
aws s3 cp --quiet reg.log $OUT/reg.log
# production path (convert_one -> ifc2step6 -> step_check), 4 concurrent x 4 threads
for k in kit_g kit_p; do
  for i in 4671ea562003 a0a1b3769d87 7c68f0c9874e; do echo "$k $i"; done
done | xargs -P 4 -n 2 sh -c '/opt/conv/env/bin/python fullpath.py "$0" "$1" >> full.log 2>&1'
for k in kit_g kit_p; do echo "$k 291547d3c10f"; done | xargs -P 2 -n 2 sh -c '/opt/conv/env/bin/python fullpath.py "$0" "$1" >> full.log 2>&1'
aws s3 cp --quiet full.log $OUT/full.log
echo REGDONE >> reg.log; aws s3 cp --quiet reg.log $OUT/reg.log
