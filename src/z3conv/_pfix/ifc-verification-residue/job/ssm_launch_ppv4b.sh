#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/targets_ppv4b.json $W/job/targets_ppv4b.json
pgrep -f "drive.py l2_vr4_rb1" >/dev/null && echo "l2 still running"
CONVF=ifc2step6_vr4.py KIT_DIR=$W/kit_vr RC_MEM_GB=40 bash $W/job/launch.sh ppv_vr4b targets_ppv4b.json 1 4 3
uptime
