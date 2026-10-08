#!/bin/bash
echo "my processes:"; ps -eo pid,etime,args | grep "audit-sds2-pipeline" | grep -v grep | cut -c1-160
du -sh /work/agentwork/audit-sds2-pipeline 2>/dev/null
if ! ps -eo args | grep "audit-sds2-pipeline" | grep -v grep -q; then
  rm -rf /work/agentwork/audit-sds2-pipeline
  echo "removed"
fi
ls /work/agentwork/
df -h /work | tail -1
