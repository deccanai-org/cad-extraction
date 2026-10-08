#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue; cd $W
S=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue
for f in drive2.py rc2.py; do aws s3 cp --quiet $S/$f $W/job/$f; done
pgrep -af "drive2.py" | cut -c1-120
CONVF=ifc2step6_612.py KIT_DIR=$W/kit612 COORD_DIR=$W/coord612 RC_MEM_GB=16 setsid nohup /opt/conv/env/bin/python $W/job/drive2.py x612_l2 $W/job/ifc2step6_612.py $W/job/targets_l2612.json --slots 3 --threads 2 --vprocs 2 --redo > $W/drive_x612_l2.log 2>&1 < /dev/null &
echo "l2 pid $!"
CONVF=ifc2step6_612.py KIT_DIR=$W/kit612 COORD_DIR=$W/coord612 RC_MEM_GB=48 setsid nohup /opt/conv/env/bin/python $W/job/drive2.py x612_ppv $W/job/ifc2step6_612.py $W/job/targets_ppv612.json --slots 1 --threads 4 --vprocs 2 --keep-step-mb 3000 --redo > $W/drive_x612_ppv.log 2>&1 < /dev/null &
echo "ppv pid $!"
