#!/bin/bash
pkill -f "xargs -P 8 -L 1 bash -c run" ; sleep 1; pkill -f "conv_only.sh /work/agentwork/cut-not-applied/kitnp7"; pkill -f "kitnp7/convert_one.py /work/agentwork/cut-not-applied/src/.*convall"; sleep 2
ps -eo pid,etime,cmd | grep "[c]onvall/kitnp7\|[x]args -P 8" | cut -c1-150; echo killed
