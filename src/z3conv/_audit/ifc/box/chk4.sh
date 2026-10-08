#!/bin/bash
ps -eo pid,etime,rss,args | grep -E 'proofs2/kit/step_check' | grep -v grep | awk '{printf "%s %s %dMB\n", $1, $2, $3/1024}'
free -g | head -2
ls /work/agentwork/audit-ifc/out | wc -l
