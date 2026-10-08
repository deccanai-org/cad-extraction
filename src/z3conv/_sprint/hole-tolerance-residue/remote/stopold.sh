#!/bin/bash
cd /work/agentwork/hole-tolerance-residue
P=$(pgrep -f "runjob2.py models2.json kit_jg,kit_jp census 16" | head -1)
if [ -n "$P" ]; then PG=$(ps -o pgid= -p $P | tr -d ' '); echo "killing my old pgid $PG ($(ps -o pid= -g $PG | wc -l) procs)"; kill -- -$PG; fi
sleep 2; pgrep -af "runjob2|fullpath" | cut -c1-150; uptime
