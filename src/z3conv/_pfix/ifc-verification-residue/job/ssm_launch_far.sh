#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue
for f in ifc2step6_pfix.py targets_far.json launch.sh; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/$f $W/job/$f; done
export RC_MEM_GB=24 CONVF=ifc2step6_pfix.py
bash $W/job/launch.sh far_pfix targets_far.json 2 2 2
