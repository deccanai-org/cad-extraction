#!/bin/bash
cd /work/agentwork/audit-ifc
echo "out $(ls out | wc -l)"
ps -eo pid,etime,rss,args | grep -E 'audit-ifc/graph.py' | grep -v grep | awk '{printf "%s %s %dMB %s\n", $1, $2, $3/1024, $6}' | head -20
for d in src/*/; do s=$(du -sm $d 2>/dev/null | cut -f1); echo "$d ${s}MB"; done | sort -k2 -n -r | head -12
