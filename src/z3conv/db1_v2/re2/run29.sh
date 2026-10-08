#!/bin/bash
W=/work/agentwork/db1v2-re2; mkdir -p $W; cd $W
aws s3 cp --quiet --recursive s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/db1v2-re2/ .
V=/work/agentwork/db1v2-val/r2
for T in 8.85_Amazon_IAD_192 9.08_ASV_Brain_and_Spine; do
  [ -f $V/$T/in.db1 ] || { echo "missing $T"; continue; }
  timeout 3000 /opt/conv/env/bin/python probe29.py $V/$T/in.db1 $V/$T/in.ifc 3 > $T.p29.txt 2>&1 &
done
wait
for T in 8.85_Amazon_IAD_192 9.08_ASV_Brain_and_Spine; do aws s3 cp --quiet $T.p29.txt s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/db1v2-re2/$T.p29.txt; done
echo done
