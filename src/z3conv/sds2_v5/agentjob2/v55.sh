#!/bin/bash
# v5.5 candidate test on data-3 jobs with piece-table / preview issues: v54f (baseline) vs v55, 4 at a time
W=/work/agentwork/sds2v54
cd $W
export AWS_DEFAULT_REGION=ap-south-1
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2v54/v55.tgz $W/v55.tgz
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2v54/getjob3.py $W/getjob3.py
mkdir -p $W/v55 && tar xzf $W/v55.tgz -C $W/v55
mkdir -p $W/jobs3
: > $W/dirs3.txt
for id in 4b7e6e9e 69174441 88fb6a52 f3e696bf; do $W/env/bin/python $W/getjob3.py $id $W/jobs3 >> $W/dirs3.txt 2>> $W/fetch3.err; done
aws s3 cp --quiet $W/dirs3.txt s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/dirs3.txt
cat $W/dirs3.txt | xargs -P 4 -I{} bash $W/conv.sh v55 {}
cat $W/dirs3.txt | xargs -P 4 -I{} bash $W/conv.sh v54f {}
date -u +%FT%TZ > $W/V55_DONE
aws s3 cp --quiet $W/V55_DONE s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/V55_DONE
