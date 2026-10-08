#!/bin/bash
echo "mine: $(ps -eo pcpu,args | grep ifc-verification-residue | grep -v grep | awk '{s+=$1} END {print s}') %cpu, procs $(pgrep -f ifc-verification-residue | wc -l)"
echo "others top:"; ps -eo pcpu,args --sort=-pcpu | grep -v ifc-verification-residue | head -8 | cut -c1-120
ps -eo pcpu,rss,args --sort=-pcpu | grep ifc-verification-residue | grep -v grep | head -12 | cut -c1-150
free -g | head -2
