#!/bin/bash
cd /work/agentwork/db1v2-re2 && aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/db1v2-re2/diag33.py .
V=/work/agentwork/db1v2-val/r2
for T in 8.07_1908_Equipment_support_s 7.82_544_Lindell_Residences 8.07_WESTOVER_HILLS_BAPTIST_H; do
  timeout 3000 /opt/conv/env/bin/python diag33.py $V/$T/in.db1 $V/$T/in.ifc $V/$T/conv.json > $T.d34.txt 2>&1 &
done; wait
for T in 8.07_1908_Equipment_support_s 7.82_544_Lindell_Residences 8.07_WESTOVER_HILLS_BAPTIST_H; do aws s3 cp --quiet $T.d34.txt s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/db1v2-re2/$T.d34.txt; done
