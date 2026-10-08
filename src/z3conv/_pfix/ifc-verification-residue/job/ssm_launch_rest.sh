#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/targets_mnc_rest.json $W/job/targets_mnc_rest.json
CONVF=ifc2step6_vr4.py RC_MEM_GB=16 bash $W/job/launch.sh far_vr4 targets_mnc_rest.json 1 2 2
CONVF=ifc2step6_vr4.py KIT_DIR=$W/kit_gp V6_FAR_VERIFY=1 RC_MEM_GB=16 bash $W/job/launch.sh far_vr4B_gp targets_mnc_rest.json 1 2 2
