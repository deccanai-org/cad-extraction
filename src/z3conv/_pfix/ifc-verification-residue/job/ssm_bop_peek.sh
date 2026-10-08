#!/bin/bash
W=/work/agentwork/ifc-verification-residue
grep -v '^\$ ' $W/w/bop_dev3/af3c44bd76cfb905/log.txt | tail -4 | cut -c1-200
ps -eo pid,rss,etimes,args | grep "bop_dev3" | grep -v grep | awk '{print $1, $2/1048576 " GB", $3 "s"}' | head -4
