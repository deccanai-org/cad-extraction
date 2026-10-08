W=/work/agentwork/ifc-volume-residue
echo "== my processes"; ps -eo pid,etime,args | grep -v grep | grep "ifc-volume-residue" | cut -c1-150
echo "== disk"; du -sh $W 2>/dev/null; du -sh $W/w/* $W/in $W/diag761 $W/v601 2>/dev/null | sort -h | tail -8
tail -2 $W/attrib_dev3.out $W/fullscan_dev3.out 2>/dev/null
