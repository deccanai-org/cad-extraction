#!/bin/bash
# rerun the 4 stage-2 v542 jobs of r542 (the first pass was cut by the SSM timeout during verify)
W=/work/agentwork/sds2v54
cd $W
export AWS_DEFAULT_REGION=ap-south-1 PYTHONUNBUFFERED=1 MPLBACKEND=Agg OMP_NUM_THREADS=1
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/c541
run() {
  V=$1; J=$2; ST=${3:-2}; N=$(basename $J); O=$W/c541/$V/$N; rm -rf $O; mkdir -p $O
  $W/env/bin/python $W/maxrss.py "$N $V" $W/c541/rss542.jsonl $W/env/bin/python -u $W/$V/sds2-step-pipeline/decode/sds2_to_step.py $J -o $O/${N}_stage$ST.step --stage $ST --verify > $O/convert.log 2>&1
  grep -av '^\*\|Transferr\|^\s*$\|\[0m\|\[32;1m' $O/convert.log > $O/${N}_stage$ST.log
  aws s3 cp --quiet --recursive $O $R/$V/$N/ --exclude "*.step" --exclude "convert.log" --exclude "*.png"
}
export -f run
export W R
for J in $W/jobs/GMS $W/jobs/AGNEWS_HS_Bldg-T* $W/jobs/TYSONS* $W/jobs/METHODIST*; do echo "v542 $J 2"; done | xargs -P 4 -L 1 bash -c 'run "$0" "$1" "$2"'
aws s3 cp --quiet $W/c541/rss542.jsonl $R/rss542.jsonl
date -u +%FT%TZ > $W/R542B_DONE
aws s3 cp --quiet $W/R542B_DONE $R/R542B_DONE
