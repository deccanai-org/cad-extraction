#!/bin/bash
# BOX-A: fleet kit 6.1.2 (current) + current coordinator grading for the ifc-verification-residue sample runs
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue; cd $W
S=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue
for f in drive2.py targets_ppv612.json targets_l2612.json l2ev.py; do aws s3 cp --quiet $S/$f $W/job/$f; done
rm -rf kit612 coord612; mkdir -p kit612 coord612
aws s3 sync --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/ifc/ kit612/ --exclude '*' --include '*.py' --include '*.json' --exclude '*/*'
for f in build_index.py grade_join.py rules.json; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/coord/$f coord612/$f; done
grep -m1 "^VERSION" kit612/ifc2step6.py; md5sum kit612/ifc2step6.py kit612/worker.py kit612/step_check.py coord612/build_index.py
cp kit612/ifc2step6.py job/ifc2step6_612.py
free -g | head -2
CONVF=ifc2step6_612.py KIT_DIR=$W/kit612 COORD_DIR=$W/coord612 RC_MEM_GB=16 setsid nohup /opt/conv/env/bin/python $W/job/drive2.py x612_l2 $W/job/ifc2step6_612.py $W/job/targets_l2612.json --slots 3 --threads 2 --vprocs 2 > $W/drive_x612_l2.log 2>&1 < /dev/null &
echo "l2 pid $!"
CONVF=ifc2step6_612.py KIT_DIR=$W/kit612 COORD_DIR=$W/coord612 RC_MEM_GB=48 setsid nohup /opt/conv/env/bin/python $W/job/drive2.py x612_ppv $W/job/ifc2step6_612.py $W/job/targets_ppv612.json --slots 1 --threads 4 --vprocs 2 --keep-step-mb 3000 > $W/drive_x612_ppv.log 2>&1 < /dev/null &
echo "ppv pid $!"
