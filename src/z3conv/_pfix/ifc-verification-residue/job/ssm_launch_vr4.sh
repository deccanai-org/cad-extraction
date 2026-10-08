#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue
for f in ifc2step6_vr4.py worker_vr.py; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/$f $W/job/$f; done
rm -rf $W/kit_vr; cp -r $W/kit $W/kit_vr; cp $W/job/worker_vr.py $W/kit_vr/worker.py
export RC_MEM_GB=24
CONVF=ifc2step6_vr4.py bash $W/job/launch.sh far_vr4 targets_far2.json 2 2 2
CONVF=ifc2step6_vr4.py KIT_DIR=$W/kit_gp V6_FAR_VERIFY=1 bash $W/job/launch.sh far_vr4B_gp targets_far2.json 1 2 2
CONVF=ifc2step6_vr4.py KIT_DIR=$W/kit_vr RB_MAX_MB=1 bash $W/job/launch.sh l2_vr4_rb1 targets_l2.json 1 2 2
sleep 2; pgrep -af "drive.py" | cut -c1-100
