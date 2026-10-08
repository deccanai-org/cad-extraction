#!/bin/bash
D=/work/agentwork/audit-sds2-v5x
echo "my processes:"; pgrep -af "agentwork/audit-sds2-v5x" | grep -v pgrep || echo none
du -sh $D 2>/dev/null
rm -rf $D && echo "removed $D"; ls /work/agentwork/
uptime
