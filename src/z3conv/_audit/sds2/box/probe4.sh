#!/bin/bash
date -u
ps -eo pid,etime,pcpu,rss,args --sort=-etime | grep -E "audit-sds2-pipeline" | grep -v grep | cut -c1-200
cat /work/agentwork/audit-sds2-pipeline/go54.log 2>/dev/null; tail -5 /work/agentwork/audit-sds2-pipeline/d5b.log 2>/dev/null
ls /work/agentwork/audit-sds2-pipeline/diag54/conv 2>/dev/null | wc -l
for d in /work/agentwork/audit-sds2-pipeline/diag54/conv/*; do echo "$d $(ls $d | tr '\n' ' ')"; tail -2 $d/convert.log 2>/dev/null; done | head -40
free -g | head -2; uptime
