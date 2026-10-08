W=/work/agentwork/ifc-volume-residue
for i in 761b25e0fe15219f f356b275dd5993f2 cdc69c9831ef0d41; do echo "== $i"; ls $W/w/dev3/$i/ 2>/dev/null | tr '\n' ' '; echo; tail -c 600 $W/w/dev3/$i/log.txt 2>/dev/null; echo; done
ps -eo pid,etime,pcpu,rss,args | grep -v grep | grep ifc2step6_dev3 | cut -c1-180
