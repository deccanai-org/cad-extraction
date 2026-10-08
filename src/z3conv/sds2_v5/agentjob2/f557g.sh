#!/bin/bash
W=/work/agentwork/sds2v54; cd $W; export AWS_DEFAULT_REGION=ap-south-1 PYTHONUNBUFFERED=1 MPLBACKEND=Agg OMP_NUM_THREADS=1
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/f557
C=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2v54
aws s3 cp --quiet $C/v557g.tgz $W/v557g.tgz; rm -rf $W/v557g; mkdir -p $W/v557g && tar xzf $W/v557g.tgz -C $W/v557g
one() {
  TAG=$1; J=$2; B=$3; N=$(basename $J); O=$W/f557/$TAG/$N; rm -rf $O; mkdir -p $O
  SDS2_VERIFY_BUDGET_S=$B timeout 14400 $W/env/bin/python -u $W/v557g/sds2-step-pipeline/decode/sds2_to_step.py $J -o $O/${N}_stage2.step --stage 2 --verify > $O/convert.log 2>&1
  grep -av '^\*\|Transferr\|^\s*$\|\[0m\|\[32;1m' $O/convert.log > $O/${N}_stage2.log
  aws s3 cp --quiet --recursive $O $R/$TAG/$N/ --exclude "*.step" --exclude "convert.log"; rm -f $O/*.step
}
export -f one; export W R
{ echo "v557g $W/jobs3/rb_ad00a536 7200"; echo "v557g_budget $(ls -d $W/jobs/160920_AGNEWS*) 15"; } | xargs -P 2 -L 1 bash -c 'one $0 $1 $2'
date -u +%FT%TZ > $W/F557G_DONE; aws s3 cp --quiet $W/F557G_DONE $R/F557G_DONE
