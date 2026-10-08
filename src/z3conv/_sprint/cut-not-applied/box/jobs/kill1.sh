#!/bin/bash
# stop my pipes1 job (only processes started from this agent's work dir)
W=/work/agentwork/cut-not-applied
P=$(pgrep -f "jobs/pipes1.sh"); echo "pipes1 pids: $P"
for p in $P; do pkill -TERM -g $(ps -o pgid= -p $p | tr -d ' ') 2>/dev/null; done
sleep 3
ps aux | grep -c "[a]gentwork/cut-not-applied"
ps -eo pid,pgid,etime,cmd | grep "[a]gentwork/cut-not-applied" | cut -c1-200 | head
