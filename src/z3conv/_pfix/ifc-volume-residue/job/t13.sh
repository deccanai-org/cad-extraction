P=$(pgrep -f "ifc-volume-residue/pkg/ifc2step6_dev3.py /work/agentwork/ifc-volume-residue/w/dev3/761b25e0fe15219f")
echo "killing $P"; ps -o pid,rss,etime,args -p $P | cut -c1-150
kill -9 $P; sleep 3; ps -o pid,rss,args -p $P | cut -c1-120; free -g | head -2
