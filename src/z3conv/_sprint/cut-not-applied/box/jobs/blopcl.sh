#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W
rm -rf kitp; cp -r kit kitp; cp stage/kitp/* kitp/
export OMP_NUM_THREADS=1
for id in a94442572f225f50 1d8972fb557e3371 4518a79a995bdee0; do
  timeout 2400 /opt/conv/ifc84/bin/python tools/blopcl_probe.py kitp src/$id.db1 > res/blopcl_$id.txt 2>&1 &
done
wait; cat res/blopcl_*.txt | cut -c1-700
