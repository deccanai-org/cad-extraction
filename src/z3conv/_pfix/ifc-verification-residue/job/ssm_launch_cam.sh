#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/targets_cam.json $W/job/targets_cam.json
CONVF=ifc2step6_vr4.py RC_MEM_GB=24 bash $W/job/launch.sh cam_vr4 targets_cam.json 1 2 2
CONVF=ifc2step6_vr4.py KIT_DIR=$W/kit_vr RB_MAX_MB=1 RC_MEM_GB=24 bash $W/job/launch.sh cam_vr4_rb1 targets_cam.json 1 2 2
