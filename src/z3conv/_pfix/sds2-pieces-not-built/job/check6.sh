W=/work/agentwork/sds2-pieces-not-built
tail -3 $W/out/diag2/fetch.err 2>/dev/null; ls $W/out/diag2/ | head -30; tail -3 $W/out/diag2.log
ps -eo pid,etimes,pcpu,rss,args | grep -E "sds2_to_step|fetch" | grep -v grep | grep -v timeout | awk '{print $1,$2,$3,int($4/1024)"MB",$7,$8}' | cut -c1-200
