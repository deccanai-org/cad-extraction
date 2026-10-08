#!/bin/bash
uptime; free -g | head -2; df -h /work | tail -1
cd /work/agentwork/cut-not-applied; ls; du -sh . 2>/dev/null; ls convall pipes2 2>/dev/null | head; ls res | head -50
ps -eo pid,user,etime,pcpu,rss,cmd --sort=-pcpu | head -15 | cut -c1-200
ps -eo pid,etime,cmd | grep "[c]ut-not-applied" | cut -c1-200
ls /work/agentwork/
