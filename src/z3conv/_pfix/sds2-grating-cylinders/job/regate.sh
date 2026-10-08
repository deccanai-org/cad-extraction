#!/bin/bash
W=/work/agentwork/sds2-grating-cylinders; cd $W
pkill -f "bash run_553g.sh"; sleep 1; pkill -f "bash gate2.sh"; sleep 1
ps -eo pid,etimes,args | grep -E "conv.sh v553|conv.sh v54g|gate2" | grep -v grep | cut -c1-200
ls -d out/v553* out/v54g 2>/dev/null; ls out/v553 out/v553g out/v54g 2>/dev/null
cat > gate3.sh <<'EOG'
#!/bin/bash
# one launch at a time: wait for < 14 of this agent's python processes and >= 90 GB free, start, hold the lock 120 s
W=/work/agentwork/sds2-grating-cylinders
(
  flock 9
  while [ "$(pgrep -f "^(/work/agentwork/sds2-grating-cylinders/)?env/bin/python" | wc -l)" -ge 14 ] || [ "$(awk '/MemAvailable/{print int($2/1048576)}' /proc/meminfo)" -lt 90 ]; do sleep 30; done
  setsid bash $W/conv.sh "$1" "$2" 9>&- < /dev/null > /dev/null 2>&1 &
  sleep 120
) 9>$W/gate.lock
EOG
cat > run_553h.sh <<'EOS'
#!/bin/bash
W=/work/agentwork/sds2-grating-cylinders; cd $W
cat q553.txt | while read v j; do n=$(basename $j); [ -d out/$v/$n ] && continue; bash gate3.sh $v $j; done
echo queued_all > Q553_DONE
EOS
setsid nohup bash run_553h.sh > run_553h.out 2>&1 < /dev/null &
echo relaunched
