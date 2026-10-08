ps -eo pid,etime,pcpu,rss,args --sort=-rss | grep -v grep | grep "ifc-volume-residue" | head -12 | cut -c1-200
uptime; free -g | head -2
