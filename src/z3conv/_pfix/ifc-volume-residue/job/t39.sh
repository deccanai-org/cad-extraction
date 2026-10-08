ps -eo pid,etime,rss,args --sort=-rss | grep -v grep | grep "ifc-volume-residue" | head -5 | cut -c1-170
