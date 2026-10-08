#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
IDS=$(for d in pipes/kitp/*; do i=$(basename $d); [ -f pipes/kit/$i/pipe.json ] && [ -f $d/pipe.json ] && echo $i; done)
/opt/conv/env/bin/python tools/pipe_cmp.py $IDS > res/pipe_cmp.txt 2>&1
aws s3 cp --quiet res/pipe_cmp.txt $OUT/pipes/pipe_cmp.txt; aws s3 cp --quiet res/pipe_cmp.json $OUT/pipes/pipe_cmp.json
cat res/pipe_cmp.txt | cut -c1-3000
