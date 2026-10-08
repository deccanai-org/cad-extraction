#!/bin/bash
cd /work/agentwork/audit-ifc
echo "out $(ls out | wc -l)  c1out $(ls c1out 2>/dev/null | wc -l)"
tail -2 scan.log; tail -2 scan2.log; tail -3 c1.log; tail -3 proofs.log; tail -3 proofs2.log
ps -eo pid,etime,rss,args | grep -E 'graph.py|graph2.py|ifc2step6|step_check' | grep -v grep | awk '{printf "%s %s %dMB ", $1, $2, $3/1024; for(i=4;i<=NF && i<8;i++) printf "%s ", $i; print ""}' | cut -c1-200 | head -20
