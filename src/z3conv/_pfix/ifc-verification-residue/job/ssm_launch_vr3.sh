#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue
for f in ifc2step6_vr3.py targets_ppv2.json; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/$f $W/job/$f; done
export RC_MEM_GB=40
CONVF=ifc2step6_vr3.py bash $W/job/launch.sh ppv_vr3 targets_ppv2.json 2 4 3
CONVF=ifc2step6_vr3.py RC_MEM_GB=16 bash $W/job/launch.sh l2_vr3 targets_l2.json 1 2 2
sleep 2; pgrep -af "drive.py" | cut -c1-110; free -g | head -2
