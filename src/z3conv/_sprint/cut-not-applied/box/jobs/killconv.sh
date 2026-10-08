#!/bin/bash
for g in 1897351 1909624; do kill -TERM -- -$g 2>/dev/null; done
pkill -f "jobs/convall.sh"; pkill -f "cut-not-applied/tools/conv_only.sh"; pkill -f "cut-not-applied/kit2/convert_one.py"; pkill -f "cut-not-applied/kitp3/convert_one.py"
sleep 3; pkill -9 -f "cut-not-applied/kit2/convert_one.py"; pkill -9 -f "cut-not-applied/kitp3/convert_one.py"
sleep 1; ps -eo pid,cmd | grep "[c]onvall\|[c]onv_only\|kitp3/convert_one\|kit2/convert_one" | cut -c1-120
cd /work/agentwork/cut-not-applied && rm -rf convall; echo cleaned
