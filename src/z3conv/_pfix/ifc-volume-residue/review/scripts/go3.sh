#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-volume-residue-review
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-volume-residue-review
cd $W
PY=/opt/conv/env/bin/python
($PY pkg/census_cmp.py pkg/census_rows.json census_cmp.jsonl --jobs 4 > census_cmp.log 2>&1; aws s3 cp --quiet census_cmp.jsonl $R/census_cmp.jsonl; aws s3 cp --quiet census_cmp.log $R/census_cmp.log) &
(for i in $(seq 1 300); do sleep 120; [ -f census_cmp.jsonl ] && aws s3 cp --quiet census_cmp.jsonl $R/census_cmp_partial.jsonl; grep -q 'CENSUS CMP DONE' census_cmp.log 2>/dev/null && break; done) &
wait
