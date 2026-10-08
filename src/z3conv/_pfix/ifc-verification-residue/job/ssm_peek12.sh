#!/bin/bash
W=/work/agentwork/ifc-verification-residue
for d in $W/w/ppv_vr3/*/; do echo "== $d"; grep -v "^\$ " $d/log.txt 2>/dev/null | tail -8 | cut -c1-200; done
ps -eo pid,rss,etimes,pcpu,args --sort=-rss | grep "ifc-verification-residue" | grep -v grep | head -6 | cut -c1-140
cat $W/wd.log 2>/dev/null | tail -3; uptime
