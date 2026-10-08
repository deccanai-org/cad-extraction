#!/bin/bash
# reviewer job 1: R (reproduce 7 sample models x 3 configs) + probe over the pool
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-volume-residue-review
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-volume-residue-review
cd $W
PY=/opt/conv/env/bin/python
(V6_VERIFY_PROCS=2 $PY pkg/batch3.py R_dev3 $W/pkg/conv_dev3 $W/pkg/kit2 pkg/models_R.json --jobs 1 > R_dev3.log 2>&1; aws s3 cp --quiet R_dev3.log $R/R_dev3.log) &
(V6_VERIFY_PROCS=2 $PY pkg/batch3.py R_comb $W/pkg/conv_comb $W/pkg/kit2 pkg/models_R.json --jobs 1 > R_comb.log 2>&1; aws s3 cp --quiet R_comb.log $R/R_comb.log) &
(V6_VERIFY_PROCS=2 $PY pkg/batch3.py R_comb3 $W/pkg/conv_comb $W/pkg/kit3 pkg/models_R.json --jobs 1 > R_comb3.log 2>&1; aws s3 cp --quiet R_comb3.log $R/R_comb3.log) &
($PY pkg/probe_all.py pkg/pool.json probe.jsonl --jobs 5 > probe.log 2>&1; aws s3 cp --quiet probe.jsonl $R/probe.jsonl; aws s3 cp --quiet probe.log $R/probe.log) &
# periodic upload of probe progress
(for i in $(seq 1 200); do sleep 120; [ -f probe.jsonl ] && aws s3 cp --quiet probe.jsonl $R/probe_partial.jsonl; grep -q 'PROBE DONE' probe.log 2>/dev/null && break; done) &
wait
echo ALL1 DONE > done1.txt; aws s3 cp --quiet done1.txt $R/done1.txt
