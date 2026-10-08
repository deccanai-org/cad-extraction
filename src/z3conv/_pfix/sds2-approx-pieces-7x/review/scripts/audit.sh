#!/bin/bash
# audit.sh JOBDIR -> base553, cand (vs base553), v556 (vs base553) piece audits
J=$1; N=$(basename "$J"); W=/work/agentwork/sds2-approx-pieces-7x-review; A=$W/audit; mkdir -p $A
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-approx-pieces-7x-review
PY=/work/agentwork/sds2v54/env/bin/python
export PYTHONUNBUFFERED=1 OMP_NUM_THREADS=1 AWS_DEFAULT_REGION=ap-south-1
cd $A
timeout 10800 $PY $W/audit.py $W/base553/sds2-step-pipeline/decode $J $A/base553__$N.json > $A/base553__$N.log 2>&1
timeout 10800 $PY $W/audit.py $W/cand/sds2-step-pipeline/decode $J $A/cand__$N.json $A/base553__$N.json > $A/cand__$N.log 2>&1
timeout 10800 $PY $W/audit.py $W/v556/sds2-step-pipeline/decode $J $A/v556__$N.json $A/base553__$N.json > $A/v556__$N.log 2>&1
for f in $A/*__$N.json $A/*__$N.log; do gzip -c $f > $f.gz; done
aws s3 cp --only-show-errors --recursive $A $R/audit/ --exclude "*" --include "*__$N.json.gz" --include "*__$N.log"
