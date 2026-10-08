uptime; nproc; free -g | head -2; df -h /work | tail -1; ls /work/agentwork/ 2>/dev/null; ps -eo pid,user,pcpu,rss,etime,args --sort=-pcpu | head -15 | cut -c1-200
