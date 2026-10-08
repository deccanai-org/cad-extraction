#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue; cd $W
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/targets_mnc612.json $W/job/targets_mnc612.json
CONVF=ifc2step6_612.py KIT_DIR=$W/kit612 COORD_DIR=$W/coord612 RC_MEM_GB=16 setsid nohup /opt/conv/env/bin/python $W/job/drive2.py x612_mnc $W/job/ifc2step6_612.py $W/job/targets_mnc612.json --slots 3 --threads 2 --vprocs 2 > $W/drive_x612_mnc.log 2>&1 < /dev/null &
echo "mnc pid $!"
