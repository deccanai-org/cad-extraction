W=/work/agentwork/ifc-volume-residue
setsid nohup bash $W/pkg/census3_all.sh > $W/census3_all.out 2>&1 < /dev/null &
echo started
