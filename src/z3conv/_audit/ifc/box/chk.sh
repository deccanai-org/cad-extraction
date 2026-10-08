#!/bin/bash
uptime
for p in $(pgrep -f 'audit-ifc/graph.py|scan.py --small' | head -6); do echo "$p $(taskset -cp $p 2>/dev/null | awk -F: '{print $2}')"; done
ls /work/agentwork/audit-ifc/out | wc -l
