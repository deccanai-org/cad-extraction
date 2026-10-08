#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/oldfit_probe.py tools/
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
for n in iron gambro 0762effe61de88c0; do ( timeout 1800 /opt/conv/env/bin/python tools/oldfit_probe.py $n > res/oldfit2_$n.txt 2>&1; aws s3 cp --quiet res/oldfit2_$n.txt $OUT/fit/ ) & done; wait
