#!/bin/bash
W=/work/agentwork/sds2v54; cd $W; export AWS_DEFAULT_REGION=ap-south-1 PYTHONUNBUFFERED=1
C=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2v54
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/afb
for f in afb2.py afb_jobs.txt v55draft.tgz; do aws s3 cp --quiet $C/$f $W/$f; done
rm -rf $W/v55draft; mkdir -p $W/v55draft && tar xzf $W/v55draft.tgz -C $W/v55draft
F=cad-disk-extract/zenitude-data-3/_state/conv/sds2/files
mkdir -p $W/afb; rm -f $W/afb/afb.jsonl
one() {
  id=$1; pk=$2
  k=$(aws s3 ls s3://bim-proprietary-data/$F/$id | awk '{print $4}' | head -1)
  [ -d $W/jobs3/t_${id:0:8} ] || $W/env/bin/python $W/getjob3k.py $F/$k $W/jobs3 t_${id:0:8} > /dev/null 2>&1
  aws s3 cp --quiet "s3://bim-proprietary-data/$pk" $W/afb/${id:0:8}_pieces.csv
  timeout 3000 $W/env/bin/python $W/afb2.py $W/jobs3/t_${id:0:8} $W/afb/${id:0:8}_pieces.csv $W/v553b/sds2-step-pipeline/decode $W/v55draft/decode >> $W/afb/afb.jsonl 2>> $W/afb/afb.err
}
export -f one; export W F
cat $W/afb_jobs.txt | grep . | xargs -P 4 -L 1 bash -c 'one $0 $1'
aws s3 cp --quiet $W/afb/afb.jsonl $R/afb.jsonl; aws s3 cp --quiet $W/afb/afb.err $R/afb.err
date -u +%FT%TZ > $W/AFB_DONE; aws s3 cp --quiet $W/AFB_DONE $R/AFB_DONE
