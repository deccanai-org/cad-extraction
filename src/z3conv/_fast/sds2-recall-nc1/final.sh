#!/bin/bash
# final pass (agent box): after the base pipeline and the v4c / v5.3 conversions finish, re-run the NC1 and IFC checks on
# every STEP (fleet + agent conversions) with the final code and rebuild out/report.json + report.md
W=/work/agentwork/sds2-recall-nc1
cd $W
for n in pipe conv; do
  P=$(cat logs/$n.pid 2>/dev/null)
  while [ -n "$P" ] && kill -0 $P 2>/dev/null; do sleep 30; done
  echo "$n finished $(date -u)"
done
T=$(date +%H%M)
mv out/nc1 out/nc1_prev_$T; mkdir -p out/nc1
mv out/ifc out/ifc_prev_$T; mkdir -p out/ifc
/opt/conv/env/bin/python run_jobs.py --phase nc1,ifc --workers 8 --ifc-workers 3 --tag final
/opt/conv/env/bin/python aggregate.py > out/aggregate_final.txt 2>&1
aws s3 cp --quiet out/aggregate_final.txt s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-recall-nc1/out/aggregate_final.txt
echo "final done $(date -u)"
