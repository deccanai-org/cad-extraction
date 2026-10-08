uptime; free -g | head -2; df -h /work | tail -1; ls /work/agentwork/; nproc
ps -eo pid,pcpu,rss,etime,args --sort=-pcpu | head -15 | cut -c1-200
