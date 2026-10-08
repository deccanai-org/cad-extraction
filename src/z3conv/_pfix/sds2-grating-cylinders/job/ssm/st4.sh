#!/bin/bash
W=/work/agentwork/sds2-grating-cylinders; cd $W
uptime; free -g | head -2
grep -v LD_PRE logs/rod2.log | tail -60 | cut -c1-300
ls out/base54 out/v55 2>/dev/null
for d in out/base54/* out/v55/*; do [ -f $d/rc.txt ] && echo "$d $(cat $d/rc.txt)"; done
