#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
PY=/opt/conv/ifc84/bin/python
mkdir -p res/trace
for id in a94442572f225f50 1d8972fb557e3371 4518a79a995bdee0 dcdf359ef4a2499b; do
  ( timeout 3000 $PY tools/trace_unbuilt.py kit src/$id.db1 > res/trace/$id.txt 2>&1; aws s3 cp --quiet res/trace/$id.txt $OUT/trace/ ) &
done
wait; echo DONE
