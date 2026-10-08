cd /work/agentwork/class1-readiness-audit
pkill -f "job/aud.py kit_k2 " ; sleep 1; pkill -f "kit_k2/convert_one.py"; sleep 1
ps -eo pid,etime,args | grep "class1-readiness-audit\|kit_k" | grep -v grep | awk '{print $1,$2,$3,$4,$5}' | head; uptime
