#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue
for f in ifc2step6_vr5.py step_check_far.py targets_far3.json; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/$f $W/job/$f; done
cp $W/job/step_check_far.py $W/kit_gp/step_check.py
CONVF=ifc2step6_vr5.py RC_MEM_GB=24 bash $W/job/launch.sh far_vr5 targets_far3.json 2 2 2
CONVF=ifc2step6_vr5.py KIT_DIR=$W/kit_gp V6_FAR_VERIFY=1 RC_MEM_GB=24 bash $W/job/launch.sh far_vr5B_gp targets_far3.json 1 2 2
uptime
