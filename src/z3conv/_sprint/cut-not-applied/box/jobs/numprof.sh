#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W
export OMP_NUM_THREADS=1
for id in dcdf359ef4a2499b 1d8972fb557e3371 4518a79a995bdee0; do
  timeout 1500 /opt/conv/ifc84/bin/python tools/numprof_probe.py kitp src/$id.db1 > res/numprof_$id.txt 2>&1 &
done
wait; cat res/numprof_*.txt | cut -c1-900
