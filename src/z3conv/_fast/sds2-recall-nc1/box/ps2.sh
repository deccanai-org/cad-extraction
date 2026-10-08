#!/bin/bash
uptime; free -g | head -2
ps -eo pid,pcpu,rss,etime,cmd --sort=-pcpu | grep sds2-recall-nc1 | grep -v grep | cut -c1-230 | head -20
tail -5 /work/agentwork/sds2-recall-nc1/logs/conv.log
ls /work/agentwork/sds2-recall-nc1/convres | wc -l
df -h /work | tail -1
