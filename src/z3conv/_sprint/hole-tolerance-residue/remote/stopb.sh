#!/bin/bash
cd /work/agentwork/hole-tolerance-residue
P=$(pgrep -f "runjob.py models2.json kit_i,kit_g,kit_p" | head -1)
if [ -n "$P" ]; then PG=$(ps -o pgid= -p $P | tr -d ' '); echo "killing my pgid $PG"; ps -o pid,args -g $PG | wc -l; kill -- -$PG; fi
P2=$(pgrep -f "bash job_reg.sh" | head -1); [ -n "$P2" ] && { PG2=$(ps -o pgid= -p $P2 | tr -d ' '); kill -- -$PG2 2>/dev/null; echo "killed job_reg pgid $PG2"; }
sleep 2; pgrep -af "harness2.py|fullpath.py|job_reg" | head; uptime
