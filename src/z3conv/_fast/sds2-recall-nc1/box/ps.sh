#!/bin/bash
uptime; free -g | head -2
ps -eo pid,pcpu,rss,etime,cmd --sort=-pcpu | grep -v "ps -eo" | head -12
ls -la /work/agentwork/sds2-recall-nc1/inv/ 2>/dev/null | head -20
