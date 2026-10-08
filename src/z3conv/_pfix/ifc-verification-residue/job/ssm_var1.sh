#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/variant_test.py $W/job/variant_test.py
cd $W/diag
setsid nohup /opt/conv/env/bin/python $W/job/variant_test.py $W/job/ifc2step6_dev3.py $W/diag/seaport.ifc 02dnNiHvr9xext7h6RlJ8V --cap-gb 12 --timeout 150 > $W/diag/var_a3717.jsonl 2> $W/diag/var_a3717.err < /dev/null &
echo started
