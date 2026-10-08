#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W
export OMP_NUM_THREADS=1
for id in a94442572f225f50 1d8972fb557e3371 4518a79a995bdee0; do
  timeout 2400 /opt/conv/ifc84/bin/python tools/newsalv_probe.py kitp src/$id.db1 > res/newsalv_$id.txt 2>&1 &
done
wait; cat res/newsalv_*.txt | cut -c1-700
