#!/bin/bash
W=/work/agentwork/ifc-verification-residue
ls -la $W/diag/far5* 2>/dev/null
cat $W/diag/far5_*.jsonl 2>/dev/null
echo ---probe; tail -5 $W/diag/probe_seaport.jsonl; tail -3 $W/diag/probe_seaport.log
ps -o pid,rss,etimes,args -p $(pgrep -f probe_kernel.py | head -1) 2>/dev/null | cut -c1-120
