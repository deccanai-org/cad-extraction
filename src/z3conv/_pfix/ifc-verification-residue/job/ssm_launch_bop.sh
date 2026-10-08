#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/targets_bop.json $W/job/targets_bop.json
CONVF=ifc2step6_dev3.py RC_MEM_GB=40 bash $W/job/launch.sh bop_dev3 targets_bop.json 1 4 3
pgrep -af "wd.sh" | head -1
