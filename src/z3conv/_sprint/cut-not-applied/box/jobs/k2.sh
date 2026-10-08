#!/bin/bash
kill -- -2891016 2>&1; sleep 1; ps -eo pid,pgid,etime,cmd | grep "[f]it_probe" | cut -c1-150
cd /work/agentwork/cut-not-applied; head -c 3000 res/fitprobe_iron.txt; echo; head -c 3000 res/fitprobe_gsk.txt
