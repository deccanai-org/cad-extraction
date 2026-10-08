#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/fitrec_probe.py tools/
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
for n in gambro 0762effe61de88c0; do ( timeout 1200 /opt/conv/env/bin/python tools/fitrec_probe.py $n > res/fitrec_$n.txt 2>&1; aws s3 cp --quiet res/fitrec_$n.txt $OUT/fit/ ) & done; wait
