#!/bin/bash
uptime; nproc; free -g | head -2; df -h /work | tail -1
echo "--- top cpu"
ps -eo pid,user,pcpu,rss,etimes,args --sort=-pcpu | head -25 | cut -c1-220
echo "--- agentwork"
ls -la /work/agentwork/ 2>/dev/null
du -sh /work/agentwork/* 2>/dev/null | head -20
