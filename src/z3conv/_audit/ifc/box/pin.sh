#!/bin/bash
# pin only this audit job's processes (cmdline under /work/agentwork/audit-ifc) to 18 cores
for p in $(pgrep -f '/work/agentwork/audit-ifc/|scan.py --small-procs|audit-ifc/job.sh'); do
  if tr '\0' ' ' < /proc/$p/cmdline 2>/dev/null | grep -q 'audit-ifc\|scan.py'; then taskset -a -cp 46-63 $p > /dev/null 2>&1; fi
done
sleep 20; uptime
ps -eo pid,psr,pcpu,args | grep -E 'graph.py|scan.py' | grep -v grep | awk '{print \$2}' | sort -n | uniq -c | head -30
