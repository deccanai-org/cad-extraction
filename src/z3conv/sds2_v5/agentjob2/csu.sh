#!/bin/bash
W=/work/agentwork/sds2v54; cd $W; export AWS_DEFAULT_REGION=ap-south-1 PYTHONUNBUFFERED=1 MPLBACKEND=Agg OMP_NUM_THREADS=1
C=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2v54
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/csu
aws s3 cp --quiet $C/v554a.tgz $W/v554a.tgz; rm -rf $W/v554a; mkdir -p $W/v554a && tar xzf $W/v554a.tgz -C $W/v554a
for ST in 1 2; do
  O=$W/csu/v554a/st$ST; rm -rf $O; mkdir -p $O
  timeout 7200 $W/env/bin/python -u $W/v554a/sds2-step-pipeline/decode/sds2_to_step.py $W/jobs3/csu -o $O/csu_stage$ST.step --stage $ST --verify > $O/convert.log 2>&1
  echo "rc=$?" >> $O/convert.log
  grep -av '^\*\|Transferr\|^\s*$\|\[0m\|\[32;1m' $O/convert.log > $O/csu_stage$ST.log
  aws s3 cp --quiet --recursive $O $R/st$ST/ --exclude "*.step" --exclude "convert.log"
done
date -u +%FT%TZ > $W/CSU_DONE; aws s3 cp --quiet $W/CSU_DONE $R/CSU_DONE
