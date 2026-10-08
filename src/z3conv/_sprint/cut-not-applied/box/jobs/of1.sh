#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/oldfit_probe.py tools/
until [ -f kitnp/.patched ]; do sleep 5; done
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
for n in iron gambro 0762effe61de88c0 6eabb07e71459be6; do ( timeout 1200 /opt/conv/env/bin/python tools/oldfit_probe.py $n > res/oldfit_$n.txt 2>&1; aws s3 cp --quiet res/oldfit_$n.txt $OUT/fit/ ) & done; wait
for n in iron gambro 0762effe61de88c0 6eabb07e71459be6; do echo "#### $n"; head -c 5000 res/oldfit_$n.txt; done
