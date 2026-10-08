#!/bin/bash
cd /work/agentwork/hole-tolerance-residue
for f in census/kit_i/*.err; do echo "== $f"; tail -5 $f; done
ps -eo pid,etime,args | grep -E "harness2" | grep -v grep | cut -c1-150
cat nc_find.log; true
