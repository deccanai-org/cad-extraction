#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue
for p in $(pgrep -f "probe_kernel.py|probe_iter.py"); do kill -9 $p; done
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/inspect_prod.py $W/job/inspect_prod.py
timeout 120 /opt/conv/env/bin/python $W/job/inspect_prod.py $W/diag/seaport.ifc 02dnNiHvr9xext7h6RlJ8V 2>&1 | head -150
