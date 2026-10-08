#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/targets_l2.json $W/job/targets_l2.json
export RC_MEM_GB=24
bash $W/job/launch.sh l2_dev3 targets_l2.json 2 2 2
