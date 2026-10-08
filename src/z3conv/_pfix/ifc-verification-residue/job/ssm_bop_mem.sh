#!/bin/bash
ps -eo pid,rss,etimes,pcpu,args | grep "bop_dev3" | grep -v grep | awk '{printf "%s %.2fGB %ss cpu%s %s\n", $1, $2/1048576, $3, $4, substr($0, index($0,$5), 90)}'
tail -3 /work/agentwork/ifc-verification-residue/wd.log
