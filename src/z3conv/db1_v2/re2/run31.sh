#!/bin/bash
cd /work/agentwork/db1v2-re2 && aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/db1v2-re2/probe31.py .
V=/work/agentwork/db1v2-val/r2
for T in 8.85_Amazon_IAD_192 9.08_ASV_Brain_and_Spine 8.85_TORAY 9.08_I8973; do
  [ -f $V/$T/in.db1 ] && timeout 3000 /opt/conv/env/bin/python probe31.py $V/$T/in.db1 $V/$T/in.ifc > $T.p31.txt 2>&1 &
done; wait
for T in 8.85_Amazon_IAD_192 9.08_ASV_Brain_and_Spine 8.85_TORAY 9.08_I8973; do aws s3 cp --quiet $T.p31.txt s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/db1v2-re2/$T.p31.txt; done; echo done
