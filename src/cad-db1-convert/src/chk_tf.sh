ps -eo pid,etime,pcpu,rss,args | grep "[t]est_final" | cut -c1-160; uptime
