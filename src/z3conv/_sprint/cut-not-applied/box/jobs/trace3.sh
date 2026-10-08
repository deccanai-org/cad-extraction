#!/bin/bash
cd /work/agentwork/cut-not-applied; cp stage/tools/trace_unbuilt.py tools/
for id in 4fa8f263f754f862 cc9bf730baa1585c dcdf359ef4a2499b 27a9febf9f71d956; do
  timeout 2400 /opt/conv/ifc84/bin/python tools/trace_unbuilt.py kitp3 src/$id.db1 > res/trace3_$id.txt 2>&1 &
done; wait
for id in 4fa8f263f754f862 cc9bf730baa1585c dcdf359ef4a2499b 27a9febf9f71d956; do grep -A3 "^==\|UNBUILT" res/trace3_$id.txt | cut -c1-300 | head -14; done
