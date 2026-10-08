#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/outline_dbg.py tools/
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
for id in a94442572f225f50 a95d70a8981d7cf7 2ffffe4d1d7811e9; do ( timeout 2400 /opt/conv/ifc84/bin/python tools/outline_dbg.py kitnp src/$id.db1 6 > res/outline_$id.txt 2>&1; aws s3 cp --quiet res/outline_$id.txt $OUT/outline/ ) & done; wait
