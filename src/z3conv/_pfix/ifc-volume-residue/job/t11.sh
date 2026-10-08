ps -eo pid,etime,args | grep -v grep | grep -E "fixtest|fullscan|batch.py|attrib" | cut -c1-200
ls /work/agentwork/ifc-volume-residue/
