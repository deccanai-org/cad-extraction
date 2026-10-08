#!/bin/bash
W=/work/agentwork/sds2-grating-cylinders; cd $W
uptime
for d in out/base54/* out/v55/* out/v55f/*; do [ -d $d ] && echo "$d $(cat $d/rc.txt 2>/dev/null || echo running)"; done
ls gr4d 2>/dev/null; grep -v LD_PRE logs/gr4d.log 2>/dev/null | cut -c1-250 | tail -12
