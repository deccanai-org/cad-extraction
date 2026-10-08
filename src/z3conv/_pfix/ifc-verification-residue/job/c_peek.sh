#!/bin/bash
W=/work/agentwork/ifc-verification-residue/sds2
cat $W/out/summary.txt 2>/dev/null; tail -3 $W/runall.log
for f in $(ls -d $W/out/*/* 2>/dev/null); do echo "== $f"; grep -v "^\*\|Transferr\|^ *$" $f/log.txt 2>/dev/null | tail -12 | cut -c1-220; tail -3 $f/err.txt | cut -c1-300; done
pgrep -af "ifc-verification-residue/sds2" | cut -c1-150
