ps -eo pid,etime,rss,args | grep -v grep | grep -E "dev3p|census3|trace" | cut -c1-170
cat /work/agentwork/ifc-volume-residue/batch_dev3p_a.out 2>/dev/null | tail -3; uptime; free -g | head -2
