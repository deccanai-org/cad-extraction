#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/probe_iter.py $W/job/probe_iter.py
cd $W/diag
setsid nohup /opt/conv/env/bin/python $W/job/probe_iter.py $W/job/ifc2step6_dev3.py $W/diag/seaport.ifc $W/diag/iter_seaport_t4.jsonl --threads 4 --limit-gb 30 > $W/diag/iter_seaport_t4.log 2>&1 < /dev/null &
echo started $!
