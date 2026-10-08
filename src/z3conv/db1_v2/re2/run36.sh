#!/bin/bash
cd /work/agentwork/db1v2-re2 && aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/db1v2-re2/diag36.py .
V=/work/agentwork/db1v2-val/r2
for T in 8.07_WESTOVER_HILLS_BAPTIST_H 8.07_1908_Equipment_support_s 8.53_Continental_Structural_P; do timeout 3000 /opt/conv/env/bin/python diag36.py $V/$T/in.db1 $V/$T/in.ifc > $T.d36.txt 2>&1 & done; wait
for T in 8.07_WESTOVER_HILLS_BAPTIST_H 8.07_1908_Equipment_support_s 8.53_Continental_Structural_P; do aws s3 cp --quiet $T.d36.txt s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/db1v2-re2/$T.d36.txt; done
