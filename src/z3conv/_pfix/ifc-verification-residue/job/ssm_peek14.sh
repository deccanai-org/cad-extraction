#!/bin/bash
W=/work/agentwork/ifc-verification-residue
for d in $W/w/ppv_vr3/*/; do echo "== $d"; grep -v "^\$ " $d/log.txt 2>/dev/null | tail -4 | cut -c1-250; done
cat $W/wd.log | tail -2; uptime; free -g | head -2
