#!/bin/bash
W=/work/agentwork/sds2v54; cd $W; export AWS_DEFAULT_REGION=ap-south-1 PYTHONUNBUFFERED=1 MPLBACKEND=Agg OMP_NUM_THREADS=1
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/f557
C=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2v54
aws s3 cp --quiet $C/v557f.tgz $W/v557f.tgz; rm -rf $W/v557f; mkdir -p $W/v557f && tar xzf $W/v557f.tgz -C $W/v557f
run() {
  V=$1; J=$2; ST=${3:-2}; N=$(basename $J); O=$W/f557/$V/$N; rm -rf $O; mkdir -p $O
  timeout 10800 $W/env/bin/python -u $W/$V/sds2-step-pipeline/decode/sds2_to_step.py $J -o $O/${N}_stage$ST.step --stage $ST --verify > $O/convert.log 2>&1
  grep -av '^\*\|Transferr\|^\s*$\|\[0m\|\[32;1m' $O/convert.log > $O/${N}_stage$ST.log
  aws s3 cp --quiet --recursive $O $R/$V/$N/ --exclude "*.step" --exclude "convert.log"; rm -f $O/*.step
}
export -f run; export W R
{ echo "v557f $W/jobs3/wp_5eed44fe 2"; echo "v557f $W/jobs3/wp_a47a1307 2"; echo "v557f $(ls -d $W/jobs/160920_AGNEWS*) 2"; echo "v557f $W/jobs/GMS 2"; } | xargs -P 4 -L 1 bash -c 'run "$0" "$1" "$2"'
date -u +%FT%TZ > $W/F557F_DONE; aws s3 cp --quiet $W/F557F_DONE $R/F557F_DONE
