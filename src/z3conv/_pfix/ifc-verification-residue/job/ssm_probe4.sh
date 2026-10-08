#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue
kill -9 595079 2>/dev/null; sleep 1
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/probe_kernel.py $W/job/probe_kernel.py
tail -2 $W/diag/probe_seaport_1800.jsonl
cd $W/diag
PROBE_VERBOSE=1 setsid nohup /opt/conv/env/bin/python $W/job/probe_kernel.py $W/job/ifc2step6_dev3.py $W/diag/seaport.ifc $W/diag/probe_seaport_v1820.jsonl --limit-gb 30 --only-openings --start 1820 --end 3100 > $W/diag/probe_seaport_v1820.log 2>&1 < /dev/null &
echo started $!; free -g | head -2
