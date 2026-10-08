#!/bin/bash
W=/work/agentwork/ifc-verification-residue
cat $W/diag/var_a3717.jsonl; tail -3 $W/diag/var_a3717.err
ps -eo pid,rss,etimes,args | grep variant_test | grep -v grep | cut -c1-150
