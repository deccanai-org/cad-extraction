#!/bin/bash
for pat in "jobs/fin3.sh" "jobs/bbp2.sh" "jobs/p15g.sh" "jobs/e15.sh" "jobs/rnd2.sh" "jobs/rnd4.sh" "jobs/k6.sh" "jobs/n2.sh"; do for p in $(pgrep -f "$pat"); do kill -- -$p 2>/dev/null; kill $p 2>/dev/null; done; done
sleep 1; pkill -f "/work/agentwork/cut-not-applied/kit" ; pkill -f "/work/agentwork/cut-not-applied/tools"; sleep 2
cd /work/agentwork/cut-not-applied; du -sh . ; find pipes pipes2 pipes3 pipes4 pipes5 ifconly convall -type f \( -name 'model.ifc' -o -name 'model.stp' -o -name 'fixed.ifc' -o -name '*.verify_parts.jsonl.gz' -o -name 'spool.bin' \) -delete 2>/dev/null; rm -rf pipes*/*/*/.v6tmp_* res/e2e/*/*.ifc res/e15/*/*.ifc 2>/dev/null; du -sh .
ps -eo pid,etime,cmd | grep "[c]ut-not-applied" | grep -v cleanup | cut -c1-120; uptime
