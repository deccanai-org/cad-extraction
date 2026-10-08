#!/bin/bash
W=/work/agentwork/sds2-pieces-not-built; cd $W; mkdir -p $W/stage $W/out
C=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-pieces-not-built
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-pieces-not-built
aws s3 cp --quiet $C/group2.py $W/stage/group2.py; aws s3 cp --quiet $C/pnb_rows_live.json $W/stage/pnb_rows_live.json
timeout 600 /opt/conv/env/bin/python $W/stage/group2.py $W/stage/pnb_rows_live.json $W/out/groups2 > $W/out/group2.log 2>&1
aws s3 cp --quiet --recursive $W/out/groups2 $R/groups2/; aws s3 cp --quiet $W/out/group2.log $R/groups2/group2.log
head -3 $W/out/group2.log; wc -l $W/out/group2.log
