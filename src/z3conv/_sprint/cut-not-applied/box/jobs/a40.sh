#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/arc40_probe.py tools/
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
for f in src/a94442572f225f50.db1 fit/p7.64.db1 src/4518a79a995bdee0.db1 fit/p9.08.db1 fit/p8.53.db1 src/1d8972fb557e3371.db1 fit/p8.85.db1; do ( n=$(basename $f .db1); timeout 1800 /opt/conv/ifc84/bin/python tools/arc40_probe.py kitnp3 $f > res/arc40_$n.txt 2>&1; aws s3 cp --quiet res/arc40_$n.txt $OUT/arc40/ ) & done; wait
