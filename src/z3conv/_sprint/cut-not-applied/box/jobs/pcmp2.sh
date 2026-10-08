#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/*.py tools/
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
export PIPE_A=pipes2/kit2 PIPE_B=pipes2/kitp2
IDS=$(for d in pipes2/kitp2/*; do i=$(basename $d); [ -f pipes2/kit2/$i/pipe.json ] && [ -f $d/pipe.json ] && echo $i; done)
echo "IDS: $IDS"
/opt/conv/env/bin/python tools/pipe_cmp.py $IDS > res/pipe_cmp2.txt 2>&1; cp res/pipe_cmp.json res/pipe_cmp2.json
/opt/conv/env/bin/python tools/hot_cmp.py $IDS > res/hot_cmp2.txt 2>&1
export PIPE_B=pipes2/kitp3
/opt/conv/env/bin/python tools/hot_cmp.py e151a8faacbce446 575da79b6096c760 > res/hot_cmp3.txt 2>&1
for f in pipe_cmp2.txt pipe_cmp2.json hot_cmp2.txt hot_cmp3.txt; do aws s3 cp --quiet res/$f $OUT/pipes2/$f; done
cut -c1-1500 res/pipe_cmp2.txt; cat res/hot_cmp2.txt | cut -c1-300; cat res/hot_cmp3.txt | cut -c1-300
