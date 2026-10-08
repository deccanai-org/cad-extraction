#!/bin/bash
cd /work/agentwork/audit-ifc
echo "out $(ls out | wc -l)"; tail -3 proofs2.log; ls -la proofs2/ 2>/dev/null | head; tail -c 600 proofs2/convert.log 2>/dev/null
ps -eo pid,etime,rss,args | grep -E 'proofs2|graph.py' | grep -v grep | awk '{printf "%s %s %dMB %s %s\n", $1, $2, $3/1024, $5, $6}' | head
