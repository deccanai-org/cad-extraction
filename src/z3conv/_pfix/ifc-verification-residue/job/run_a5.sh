#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue; cd $W
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/step_check_2r.py $W/job/step_check_2r.py
rm -rf kit612sr; cp -r kit612 kit612sr; cp $W/job/step_check_2r.py kit612sr/step_check.py
md5sum job/ifc2step6_vr9.py kit612sr/step_check.py kit612/step_check.py
for spec in "x612sr_mnc ifc2step6_612.py kit612sr" "xvr_mnc ifc2step6_vr9.py kit612" "xvrsr_mnc ifc2step6_vr9.py kit612sr"; do
  set -- $spec
  KIT_DIR=$W/$3 COORD_DIR=$W/coord612 RC_MEM_GB=16 setsid nohup /opt/conv/env/bin/python $W/job/drive2.py $1 $W/job/$2 $W/job/targets_mnc612.json --slots 2 --threads 2 --vprocs 2 > $W/drive_$1.log 2>&1 < /dev/null &
  echo "$1 pid $!"
done
