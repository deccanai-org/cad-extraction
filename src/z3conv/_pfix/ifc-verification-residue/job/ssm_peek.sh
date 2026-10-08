#!/bin/bash
W=/work/agentwork/ifc-verification-residue
uptime; free -g | head -2
for d in $W/w/ppv_dev3/*/ $W/w/mnc_dev3/d713eae4bf9dd247/; do echo "== $d"; ls -la $d | head -20; tail -c 1500 $d/log.txt 2>/dev/null; echo; done
ps -eo pid,pcpu,rss,etimes,args --sort=-rss | grep -E "ifc-verification-residue" | grep -v grep | head -20 | cut -c1-220
