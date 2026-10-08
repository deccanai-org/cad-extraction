#!/bin/bash
WD=/work/agentwork/sds2-grating-cylinders; cd $WD
uptime
ls gr2 rod1 2>/dev/null
grep -v LD_PRELOAD logs/gr2.log 2>/dev/null | tail -12 | cut -c1-300
grep -v LD_PRELOAD logs/rod1.log 2>/dev/null | tail -12 | cut -c1-300
ps -eo pid,pcpu,rss,etime,args | grep -E "gr2.py|rod1.py|getjobs|run_a2" | grep -v grep | cut -c1-160
