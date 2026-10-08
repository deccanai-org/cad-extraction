W=/work/agentwork/ifc-volume-residue
ls -la $W/fixtest_* $W/diag761/
tail -3 $W/fixtest_224b.log | cut -c1-300
ps -eo pid,etime,args | grep -v grep | grep -E "fixtest|bisect_mem|census3" | cut -c1-160
