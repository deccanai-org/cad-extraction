#!/bin/bash
W=/work/agentwork/sds2v54; cd $W; export AWS_DEFAULT_REGION=ap-south-1 PYTHONUNBUFFERED=1
C=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2v54
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/nc1
for f in nc1cut.py v554c.tgz; do aws s3 cp --quiet $C/$f $W/$f; done
rm -rf $W/v554c; mkdir -p $W/v554c && tar xzf $W/v554c.tgz -C $W/v554c
rm -f $W/nc1/nc1cut.jsonl
echo 7b40c0c5683f62cc2f382c90 425c2f6c4282287cc9ffdc30 fcf299e7ec29c9e7855f6f21 47623a2db739778a1c12e4e8 155c96b42bc64cdfe9dbb3f9 2906268b27dbda74a63a44c9 5c14d28b72279c81a73598d9 85d4cbd8176222b0900afdf8 6e9e3214c04ce23fdda24038 | tr ' ' '\n' | xargs -P 4 -n 1 timeout 3600 $W/env/bin/python $W/nc1cut.py $W/v554c/sds2-step-pipeline/decode $W/nc1/nc1cut.jsonl > $W/nc1/nc1cut.out 2>&1
aws s3 cp --quiet $W/nc1/nc1cut.jsonl $R/nc1cut.jsonl
date -u +%FT%TZ > $W/NC1CUT_DONE; aws s3 cp --quiet $W/NC1CUT_DONE $R/NC1CUT_DONE
