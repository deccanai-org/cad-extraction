#!/bin/bash
cd /work/agentwork/audit-ifc
echo "out $(ls out | wc -l)"
ps -eo pid,etime,rss,args | grep -E 'audit-ifc/graph.py' | grep -v grep | awk '{printf "%s %s %dMB %s %s\n", $1, $2, $3/1024, $4, $6}' | head -20
