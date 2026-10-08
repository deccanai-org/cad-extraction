#!/bin/bash
WD=/work/agentwork/sds2-grating-cylinders; cd $WD
uptime
ls rod1 2>/dev/null
grep -v LD_PRELOAD logs/rod1.log 2>/dev/null | tail -20 | cut -c1-400
grep -v LD_PRELOAD logs/gr4.log 2>/dev/null | tail -20 | cut -c1-400
ps -eo pid,pcpu,rss,etime,args | grep -E "gr2.py|rod1.py|gr4.py|getjobs" | grep -v grep | cut -c1-200
