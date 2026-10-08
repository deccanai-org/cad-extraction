#!/bin/bash
W=/work/agentwork/sds2v54; cd $W; export AWS_DEFAULT_REGION=ap-south-1 PYTHONUNBUFFERED=1
C=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2v54
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/nomem
for f in nomem_diag.py nomem_ids.txt; do aws s3 cp --quiet $C/$f $W/$f; done
mkdir -p $W/jobs_nm $W/nomem; rm -f $W/nomem/diag.jsonl
cat $W/nomem_ids.txt | grep . | xargs -P 4 -n 5 timeout 3000 nice -n 5 $W/env/bin/python $W/nomem_diag.py $W/v554g/sds2-step-pipeline/decode $W/nomem/diag.jsonl > $W/nomem/diag.out 2>&1
aws s3 cp --quiet $W/nomem/diag.jsonl $R/diag.jsonl
date -u +%FT%TZ > $W/NOMEM_DONE; aws s3 cp --quiet $W/NOMEM_DONE $R/NOMEM_DONE
