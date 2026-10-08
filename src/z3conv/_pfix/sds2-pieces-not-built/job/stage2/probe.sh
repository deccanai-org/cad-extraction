W=/work/agentwork/sds2-pieces-not-built
uptime; nproc; free -g | head -2; df -h /work | tail -1
ls $W 2>/dev/null | head; du -sh $W/jobs 2>/dev/null; ls $W/jobs 2>/dev/null | wc -l
ls $W/trees 2>/dev/null; ls $W/env/bin/python 2>/dev/null
ps -eo pid,etimes,pcpu,rss,args --sort=-pcpu | grep -v "ps -eo" | head -25
