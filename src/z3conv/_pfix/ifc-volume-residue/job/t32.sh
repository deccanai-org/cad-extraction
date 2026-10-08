ps -eo pid,etime,pcpu,rss,args --sort=-rss | grep -v grep | grep "ifc-volume-residue" | head -8 | cut -c1-190
tail -3 /work/agentwork/ifc-volume-residue/batch_dev3p.log
