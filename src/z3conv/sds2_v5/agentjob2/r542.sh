#!/bin/bash
# v5.4.2 (joist regression fix) control regression: same commands as c541 (v541 outputs exist), + 19002-IMS6 stage 1
W=/work/agentwork/sds2v54
cd $W
export AWS_DEFAULT_REGION=ap-south-1 PYTHONUNBUFFERED=1 MPLBACKEND=Agg OMP_NUM_THREADS=1
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/c541
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2v54/v542.tgz $W/v542.tgz
rm -rf $W/v542; mkdir -p $W/v542 && tar xzf $W/v542.tgz -C $W/v542
run() {
  V=$1; J=$2; ST=${3:-2}; N=$(basename $J); O=$W/c541/$V/$N; mkdir -p $O
  VF="--verify"
  $W/env/bin/python $W/maxrss.py "$N $V" $W/c541/rss542.jsonl $W/env/bin/python -u $W/$V/sds2-step-pipeline/decode/sds2_to_step.py $J -o $O/${N}_stage$ST.step --stage $ST $VF > $O/convert.log 2>&1
  grep -av '^\*\|Transferr\|^\s*$\|\[0m\|\[32;1m' $O/convert.log > $O/${N}_stage$ST.log
  aws s3 cp --quiet --recursive $O $R/$V/$N/ --exclude "*.step" --exclude "convert.log" --exclude "*.png"
}
export -f run
export W R
mkdir -p $W/jobs3
[ -d $W/jobs3/19002-IMS6_JOB_fb1cae ] || $W/env/bin/python $W/getjob3.py fb1cae54 $W/jobs3 > /dev/null 2>> $W/fetch3.err
{
for J in $W/jobs/GMS $W/jobs/160920_AGNEWS* $W/jobs/AGNEWS_HS_Bldg-T* $W/jobs/TYSONS* $W/jobs/METHODIST*; do echo "v542 $J 2"; done
echo "v542 $W/jobs3/19002-IMS6_JOB_fb1cae 1"
echo "v541 $W/jobs3/19002-IMS6_JOB_fb1cae 1"
} | xargs -P 8 -L 1 bash -c 'run "$0" "$1" "$2"'
aws s3 cp --quiet $W/c541/rss542.jsonl $R/rss542.jsonl
date -u +%FT%TZ > $W/R542_DONE
aws s3 cp --quiet $W/R542_DONE $R/R542_DONE
