#!/bin/bash
W=/work/agentwork/ifc-verification-residue
for p in $(pgrep -f "ifc2step6_vr9.py $W/diag/seaport.ifc"); do kill -9 $p; done
pkill -9 -f "w/seaport_vr9/.v6tmp" 2>/dev/null
sleep 1; rm -rf $W/w/seaport_vr9; mkdir -p $W/w/seaport_vr9; cd $W/w/seaport_vr9
DEFLECTION=0.005 ANG_DEFLECTION=0.6 setsid nohup /opt/conv/env/bin/python $W/job/ifc2step6_vr9.py $W/diag/seaport.ifc $W/w/seaport_vr9/out.step --mode hybrid --prec 2 --threads 4 > $W/w/seaport_vr9/log.txt 2>&1 < /dev/null &
echo seaport pid $!
