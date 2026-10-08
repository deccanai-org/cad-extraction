hostname; uptime; nproc; free -g | head -2; df -h /work 2>/dev/null | tail -1; ls /work/agentwork 2>/dev/null; ps -eo pid,pcpu,etime,args --sort=-pcpu | head -8 | cut -c1-200
