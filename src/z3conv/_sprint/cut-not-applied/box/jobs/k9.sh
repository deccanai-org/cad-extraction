#!/bin/bash
for pat in "jobs/c8.sh" "jobs/p15.sh" "jobs/fin2.sh"; do for p in $(pgrep -f "$pat"); do kill -- -$p 2>/dev/null; kill $p 2>/dev/null; done; done
sleep 1
pkill -f "conv_only.sh /work/agentwork/cut-not-applied/kitnp8"; pkill -f "kitnp8/convert_one.py /work/agentwork/cut-not-applied/src/.*convall"
pkill -f "pipes5/kitnp7/"; pkill -f "pipes5/kitnp8/"; pkill -f "pipe.sh /work/agentwork/cut-not-applied/kitnp7"; pkill -f "pipe.sh /work/agentwork/cut-not-applied/kitnp8"
sleep 2; ps -eo pid,etime,cmd | grep "[c]ut-not-applied" | grep -v "k9.sh" | cut -c1-170
