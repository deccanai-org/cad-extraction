#!/bin/bash
cd /work/agentwork/audit-ifc
cat rerun4.log | tail -3
for i in 281ab275e7922d27 83b1b55619e6c2a1 ab2cbaa2225f367a d615945ae74d80df; do ls out/${i}*.json 2>/dev/null | head -1; done
ps -eo pid,etime,args | grep -E 'audit-ifc' | grep -v grep | cut -c1-140
