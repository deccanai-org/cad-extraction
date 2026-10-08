#!/bin/bash
for p in $(pgrep -f "jobs/tr13.sh"); do kill -- -$p 2>/dev/null; kill $p; done
pkill -f "pipes3/nofit/truth_gambro"; pkill -f "pipes3/fit/truth_gambro"; pkill -f "pipes5/kitnp7/"; pkill -f "pipes5/kitn/truth_iron"; sleep 2
cd /work/agentwork/cut-not-applied; rm -rf pipes5/kitnp7 pipes5/kitnp8 pipes5/kitn/truth_iron pipes5/kitn/6eabb07e71459be6 convall/kitnp8 convall/kitnp7
ps -eo pid,etime,cmd | grep "[c]ut-not-applied" | grep -v "k10.sh" | cut -c1-150; uptime
