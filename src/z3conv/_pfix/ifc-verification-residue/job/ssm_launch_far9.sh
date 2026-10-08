#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/targets_far4.json $W/job/targets_far4.json
CONVF=ifc2step6_vr9.py RC_MEM_GB=24 bash $W/job/launch.sh far_vr9 targets_far4.json 1 2 2
CONVF=ifc2step6_vr9.py KIT_DIR=$W/kit_gp V6_FAR_VERIFY=1 RC_MEM_GB=24 bash $W/job/launch.sh far_vr9F_gp targets_far4.json 1 2 2
uptime
