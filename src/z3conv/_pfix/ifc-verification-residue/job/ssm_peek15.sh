#!/bin/bash
W=/work/agentwork/ifc-verification-residue
for d in $W/w/ppv_vr3/beeeacea7d2d7546 $W/w/ppv_vr4b/2c0f7a89ddf2d595 $W/w/far_vr4B_gp/d713eae4bf9dd247; do echo "== $d"; grep -v "^\$ " $d/log.txt 2>/dev/null | grep -v '^{' | tail -4 | cut -c1-200; done
ps -eo pid,rss,args --sort=-rss | grep "ifc-verification-residue" | grep -v grep | head -4 | cut -c1-120
cat $W/wd.log | tail -2; uptime; free -g | head -2
