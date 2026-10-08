#!/bin/bash
W=/work/agentwork/sds2-grating-cylinders; cd $W
ls gr4b/; grep -v LD_PRE logs/gr4b.log | tail -8 | cut -c1-400
ps -eo pid,etime,args | grep "gr4.py" | grep -v grep | grep -v timeout | awk '{print $1, $2, $NF}'
