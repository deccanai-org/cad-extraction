W=/work/agentwork/ifc-volume-residue
chmod +x $W/pkg/*.sh
setsid nohup bash $W/pkg/attrib_all.sh dev3 > $W/attrib_dev3.out 2>&1 < /dev/null &
echo started $!
uptime
