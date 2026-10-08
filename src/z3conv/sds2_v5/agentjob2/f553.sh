#!/bin/bash
# final v5.5.3 tree (v553b: + read-back counts open surfaces per part): control + evidence
W=/work/agentwork/sds2v54
cd $W
export AWS_DEFAULT_REGION=ap-south-1 PYTHONUNBUFFERED=1 MPLBACKEND=Agg OMP_NUM_THREADS=1
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/f553
C=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2v54
aws s3 cp --quiet $C/v553b.tgz $W/v553b.tgz; rm -rf $W/v553b; mkdir -p $W/v553b && tar xzf $W/v553b.tgz -C $W/v553b
run() {
  V=$1; J=$2; ST=${3:-2}; N=$(basename $J); O=$W/f553/$V/$N; rm -rf $O; mkdir -p $O
  timeout 10800 $W/env/bin/python $W/maxrss.py "$N $V" $W/f553/rss.jsonl $W/env/bin/python -u $W/$V/sds2-step-pipeline/decode/sds2_to_step.py $J -o $O/${N}_stage$ST.step --stage $ST --verify > $O/convert.log 2>&1
  grep -av '^\*\|Transferr\|^\s*$\|\[0m\|\[32;1m' $O/convert.log > $O/${N}_stage$ST.log
  aws s3 cp --quiet --recursive $O $R/$V/$N/ --exclude "*.step" --exclude "convert.log"
}
export -f run
export W R
mkdir -p $W/f553
{
for J in $W/jobs/METHODIST* $W/jobs/GMS $W/jobs/AGNEWS_HS_Bldg-T* $W/jobs/TYSONS* $W/jobs/160920_AGNEWS*; do echo "v553b $J 2"; done
for id in 23c10723 606dfec9 11be3648 7699a4a7 b9c720b9 0965ed04 0e6cc241; do echo "v553b $W/jobs3/ev_$id 2"; done
echo "v553b $W/jobs3/19002-IMS6_JOB_fb1cae 1"
} | xargs -P 5 -L 1 bash -c 'run "$0" "$1" "$2"'
aws s3 cp --quiet $W/f553/rss.jsonl $R/rss.jsonl
date -u +%FT%TZ > $W/F553_DONE; aws s3 cp --quiet $W/F553_DONE $R/F553_DONE
