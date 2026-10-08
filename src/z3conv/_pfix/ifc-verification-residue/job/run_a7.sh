#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue; cd $W
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/targets_l2small.json $W/job/targets_l2small.json
KIT_DIR=$W/kit612 COORD_DIR=$W/coord612 RC_MEM_GB=16 setsid nohup /opt/conv/env/bin/python $W/job/drive2.py xfar_off_l2 $W/job/ifc2step6_612far.py $W/job/targets_l2small.json --slots 3 --threads 2 --vprocs 2 > $W/drive_xfar_off_l2.log 2>&1 < /dev/null &
echo "off pid $!"
V6_FAR_ALWAYS=1 KIT_DIR=$W/kit612sr COORD_DIR=$W/coord612 RC_MEM_GB=16 setsid nohup /opt/conv/env/bin/python $W/job/drive2.py xfar_on_l2 $W/job/ifc2step6_612far.py $W/job/targets_l2small.json --slots 3 --threads 2 --vprocs 2 > $W/drive_xfar_on_l2.log 2>&1 < /dev/null &
echo "on pid $!"
