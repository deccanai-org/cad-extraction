#!/bin/bash
cd /work/agentwork/db1v2-re2 && aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/db1v2-re2/probe32.py .
V=/work/agentwork/db1v2-val/r2
for T in 9.08_ASV_Brain_and_Spine 9.08_I8973; do timeout 3000 /opt/conv/env/bin/python probe32.py $V/$T/in.db1 $V/$T/in.ifc > $T.p32.txt 2>&1 & done; wait
for T in 9.08_ASV_Brain_and_Spine 9.08_I8973; do aws s3 cp --quiet $T.p32.txt s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/db1v2-re2/$T.p32.txt; done
