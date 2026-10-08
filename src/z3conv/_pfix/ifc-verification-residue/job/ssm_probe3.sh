#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/probe_kernel.py $W/job/probe_kernel.py
cd $W/diag
# stop the slow sequential probe (it is at ~k=520); ranges in parallel instead
pkill -f "probe_kernel.py .*probe_seaport.jsonl" ; sleep 1
P=/opt/conv/env/bin/python
setsid nohup $P $W/job/probe_iter.py $W/job/ifc2step6_dev3.py $W/diag/seaport.ifc $W/diag/iter_seaport_c500.jsonl --threads 4 --limit-gb 30 --chunk 500 > $W/diag/iter_seaport_c500.log 2>&1 < /dev/null &
for r in "500 1800" "1800 3100" "3100 4400" "4400 5700" "5700 6900" "6900 8100"; do
  set -- $r
  setsid nohup $P $W/job/probe_kernel.py $W/job/ifc2step6_dev3.py $W/diag/seaport.ifc $W/diag/probe_seaport_$1.jsonl --limit-gb 30 --only-openings --start $1 --end $2 > $W/diag/probe_seaport_$1.log 2>&1 < /dev/null &
done
sleep 2; pgrep -af "probe_" | cut -c1-140
