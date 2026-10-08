#!/bin/bash
cd /work/agentwork/db1v2-re2 && aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/db1v2-re2/diag35.py . && aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/db1v2-val/code/db1bolts2.py /work/agentwork/db1v2-val/code/db1bolts2.py
V=/work/agentwork/db1v2-val/r2
for T in 8.07_WESTOVER_HILLS_BAPTIST_H 8.07_1908_Equipment_support_s 8.53_BOBBY_JONES_MOLDTEK 7.64_E-45_Check; do timeout 3000 /opt/conv/env/bin/python diag35.py $V/$T/in.db1 $V/$T/in.ifc > $T.d35.txt 2>&1 & done; wait
for T in 8.07_WESTOVER_HILLS_BAPTIST_H 8.07_1908_Equipment_support_s 8.53_BOBBY_JONES_MOLDTEK 7.64_E-45_Check; do aws s3 cp --quiet $T.d35.txt s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/db1v2-re2/$T.d35.txt; done
