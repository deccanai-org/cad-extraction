#!/bin/bash
# v5.4 (v54g) vs v5.4.1 (v541): identical outputs + peak RSS / wall of the full fleet command on 5 validation jobs
W=/work/agentwork/sds2v54
cd $W
export AWS_DEFAULT_REGION=ap-south-1 PYTHONUNBUFFERED=1 MPLBACKEND=Agg OMP_NUM_THREADS=1
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/c541
mkdir -p $W/c541
: > $W/c541/rss.jsonl
run() {
  V=$1; J=$2; N=$(basename $J); O=$W/c541/$V/$N; mkdir -p $O
  $W/env/bin/python $W/maxrss.py "$N $V" $W/c541/rss.jsonl $W/env/bin/python -u $W/$V/sds2-step-pipeline/decode/sds2_to_step.py $J -o $O/${N}_stage2.step --stage 2 --verify > $O/convert.log 2>&1
  grep -av '^\*\|Transferr\|^\s*$\|\[0m\|\[32;1m' $O/convert.log > $O/${N}_stage2.log
  aws s3 cp --quiet --recursive $O $R/$V/$N/ --exclude "*.step" --exclude "convert.log" --exclude "*.png"
}
export -f run
export W R
for J in $W/jobs/GMS $W/jobs/160920_AGNEWS* $W/jobs/AGNEWS_HS_Bldg-T* $W/jobs/TYSONS* $W/jobs/METHODIST*; do
  for V in v54g v541; do echo "$V $J"; done
done | xargs -P 10 -L 1 bash -c 'run "$0" "$1"'
aws s3 cp --quiet $W/c541/rss.jsonl $R/rss.jsonl
date -u +%FT%TZ > $W/C541_DONE
aws s3 cp --quiet $W/C541_DONE $R/C541_DONE
