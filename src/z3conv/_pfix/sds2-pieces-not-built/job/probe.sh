uptime; nproc; free -g | head -2; df -h /work 2>/dev/null | tail -1
ls /work/agentwork/ 2>/dev/null
ps -eo pid,etimes,pcpu,rss,args --sort=-pcpu | head -15 | cut -c1-200
ls /work/agentwork/sds2v54/ 2>/dev/null | head -30
ls /work/agentwork/sds2v54/jobs /work/agentwork/sds2v54/jobs3 2>/dev/null | head -60
