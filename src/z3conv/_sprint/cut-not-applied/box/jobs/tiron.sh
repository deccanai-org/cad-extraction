#!/bin/bash
cd /work/agentwork/cut-not-applied; cp stage/tools/truth_cmp.py tools/
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
for n in iron gsk; do timeout 1200 /opt/conv/env/bin/python tools/truth_cmp.py $n > res/truth_$n.txt 2>&1; aws s3 cp --quiet res/truth_$n.txt $OUT/truth/; cut -c1-400 res/truth_$n.txt; done
