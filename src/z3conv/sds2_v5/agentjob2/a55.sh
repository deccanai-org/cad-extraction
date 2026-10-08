#!/bin/bash
# v5.5 approx-piece test: jobs with approximate pieces on 7.x; v541 (v5.4.1) vs v55b (+ B-rep spike / cap repair)
W=/work/agentwork/sds2v54
cd $W
export AWS_DEFAULT_REGION=ap-south-1
for v in v541 v55b; do
  aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2v54/$v.tgz $W/$v.tgz
  rm -rf $W/$v; mkdir -p $W/$v && tar xzf $W/$v.tgz -C $W/$v
done
: > $W/a_dirs.txt
for id in 15d6a470 16a2af6a 0c7dd60e 85b25ab5 5f7b3e43 3a219024; do
  $W/env/bin/python $W/getjob.py $id $W/jobs >> $W/a_dirs.txt 2>> $W/fetch_a.err
done
ls -d $W/jobs/METHODIST* $W/jobs/CHOWNS* >> $W/a_dirs.txt
aws s3 cp --quiet $W/a_dirs.txt s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/a_dirs.txt
cat $W/a_dirs.txt | xargs -P 8 -I{} bash $W/conv.sh v55b {}
cat $W/a_dirs.txt | xargs -P 8 -I{} bash $W/conv.sh v541 {}
date -u +%FT%TZ > $W/A55_DONE
aws s3 cp --quiet $W/A55_DONE s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/A55_DONE
