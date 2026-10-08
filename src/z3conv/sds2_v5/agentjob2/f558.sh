#!/bin/bash
W=/work/agentwork/sds2v54; cd $W; export AWS_DEFAULT_REGION=ap-south-1 PYTHONUNBUFFERED=1 MPLBACKEND=Agg OMP_NUM_THREADS=1
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/f558
C=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2v54
aws s3 cp --quiet $C/v558a.tgz $W/v558a.tgz; rm -rf $W/v558a; mkdir -p $W/v558a && tar xzf $W/v558a.tgz -C $W/v558a
one() {
  TAG=$1; J=$2; B=$3; N=$(basename $J); O=$W/f558/$TAG/$N; rm -rf $O; mkdir -p $O
  SDS2_VERIFY_BUDGET_S=$B timeout 14400 $W/env/bin/python -u $W/v558a/sds2-step-pipeline/decode/sds2_to_step.py $J -o $O/${N}_stage2.step --stage 2 --verify > $O/convert.log 2>&1
  grep -av '^\*\|Transferr\|^\s*$\|\[0m\|\[32;1m' $O/convert.log > $O/${N}_stage2.log
  aws s3 cp --quiet --recursive $O $R/$TAG/$N/ --exclude "*.step" --exclude "convert.log"; rm -f $O/*.step
}
export -f one; export W R
{ echo "v558a $W/jobs3/t_319570f4 7200"; echo "v558a $(ls -d $W/jobs/AGNEWS_HS_Bldg-T*) 7200"; echo "v558a $W/jobs/GMS 7200"; } | xargs -P 3 -L 1 bash -c 'one $0 $1 $2'
date -u +%FT%TZ > $W/F558_DONE; aws s3 cp --quiet $W/F558_DONE $R/F558_DONE
