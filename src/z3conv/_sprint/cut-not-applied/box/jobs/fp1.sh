#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/fit_probe.py tools/
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
for n in iron gambro gsk; do ( timeout 1500 /opt/conv/env/bin/python tools/fit_probe.py $n > res/fitprobe_$n.txt 2>&1; aws s3 cp --quiet res/fitprobe_$n.txt $OUT/fit/fitprobe_$n.txt ) & done; wait
echo FPDONE
