#!/bin/bash
ps -eo pid,etime,pcpu,rss,args --sort=-etime | grep -E "audit-sds2-pipeline" | grep -v grep | cut -c1-220
ls /work/agentwork/audit-sds2-pipeline/diag/conv/ | wc -l
ls -la /work/agentwork/audit-sds2-pipeline/diag/conv/4d1080fd01e2daddd8e08a1d /work/agentwork/audit-sds2-pipeline/diag/conv/eae166ac3c2c64dd2ddc5bd2 2>&1 | head
tail -3 /work/agentwork/audit-sds2-pipeline/diag/conv/4d1080fd01e2daddd8e08a1d/convert.log 2>/dev/null
tail -3 /work/agentwork/audit-sds2-pipeline/diag/conv/eae166ac3c2c64dd2ddc5bd2/convert.log 2>/dev/null
tail -5 /work/agentwork/audit-sds2-pipeline/diag.log
