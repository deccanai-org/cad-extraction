#!/bin/bash
W=/work/agentwork/sds2v54; cd $W; export AWS_DEFAULT_REGION=ap-south-1 PYTHONUNBUFFERED=1
C=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2v54
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/afb
for f in afb3.py v554b.tgz; do aws s3 cp --quiet $C/$f $W/$f; done
rm -rf $W/v554b; mkdir -p $W/v554b && tar xzf $W/v554b.tgz -C $W/v554b
rm -f $W/afb/afb3.jsonl
for t in v553b v554b; do for id in 00b3fcb9 5ce1bf4b 859650c1 9ab5fb14 319570f4 d1bf0fc7 f16781fc; do echo "$t $id"; done; done | xargs -P 7 -L 1 bash -c 'timeout 3000 /work/agentwork/sds2v54/env/bin/python /work/agentwork/sds2v54/afb3.py /work/agentwork/sds2v54/$0/sds2-step-pipeline/decode /work/agentwork/sds2v54/jobs3/t_$1 /work/agentwork/sds2v54/afb/$1_pieces.csv >> /work/agentwork/sds2v54/afb/afb3.jsonl 2>> /work/agentwork/sds2v54/afb/afb3.err'
aws s3 cp --quiet $W/afb/afb3.jsonl $R/afb3.jsonl; aws s3 cp --quiet $W/afb/afb3.err $R/afb3.err
date -u +%FT%TZ > $W/AFB3_DONE; aws s3 cp --quiet $W/AFB3_DONE $R/AFB3_DONE
