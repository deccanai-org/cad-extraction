#!/bin/bash
W=/work/agentwork/sds2v54; cd $W; export AWS_DEFAULT_REGION=ap-south-1 PYTHONUNBUFFERED=1
C=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2v54
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/next
for f in joistrt.py refdiag.py; do aws s3 cp --quiet $C/$f $W/$f; done
F=cad-disk-extract/zenitude-data-3/_state/conv/sds2/files
mkdir -p $W/next
for id in 0535bdbb 4c381a54; do
  [ -d $W/jobs3/j_$id ] || { k=$(aws s3 ls s3://bim-proprietary-data/$F/$id | awk '{print $4}' | head -1); $W/env/bin/python $W/getjob3k.py $F/$k $W/jobs3 j_$id > /dev/null 2>&1; }
  timeout 3600 $W/env/bin/python $W/joistrt.py $W/v558b/sds2-step-pipeline/decode $W/jobs3/j_$id $W/next/joist_$id.json > $W/next/joist_$id.out 2>&1
done
rm -f $W/next/cal.jsonl
timeout 3600 $W/env/bin/python $W/refdiag.py $W/v558b/sds2-step-pipeline/decode $W/next/cal.jsonl 18e77755 58c96961 6eeedc27 7fa1c983 94b59c49 e1304b91 > $W/next/cal.out 2>&1
aws s3 cp --quiet --recursive $W/next $R/
date -u +%FT%TZ > $W/NEXT_DONE; aws s3 cp --quiet $W/NEXT_DONE $R/NEXT_DONE
