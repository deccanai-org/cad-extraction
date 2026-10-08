#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
mkdir -p /work/agentwork/ifc-verification-residue/job
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/setup_box.sh /work/agentwork/ifc-verification-residue/job/setup_box.sh
bash /work/agentwork/ifc-verification-residue/job/setup_box.sh 2>&1 | tail -60
