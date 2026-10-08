#!/bin/bash
# v5.5.1 (absurd-extent fix) before/after on the evidence jobs (v541 vs v551) + control regression (v551 vs c541/v541)
W=/work/agentwork/sds2v54
cd $W
export AWS_DEFAULT_REGION=ap-south-1 PYTHONUNBUFFERED=1 MPLBACKEND=Agg OMP_NUM_THREADS=1
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/a551
C=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2v54
aws s3 cp --quiet $C/v551.tgz $W/v551.tgz; aws s3 cp --quiet $C/getjob3k.py $W/getjob3k.py
rm -rf $W/v551; mkdir -p $W/v551 && tar xzf $W/v551.tgz -C $W/v551
F=cad-disk-extract/zenitude-data-3/_state/conv/sds2/files
mkdir -p $W/jobs3
fetch() {  # id8 -> job dir (files manifest found by listing, works for jobs outside jobs.json)
  k=$(aws s3 ls s3://bim-proprietary-data/$F/$1 | awk '{print $4}' | head -1)
  [ -d $W/jobs3/ev_$1 ] || $W/env/bin/python $W/getjob3k.py $F/$k $W/jobs3 ev_$1 > /dev/null 2>> $W/fetch3.err
}
for id in 7699a4a7 b9c720b9 4e990883 bf938cf8 30ff95cd 3adae7db f0c2c894; do fetch $id; done
run() {
  V=$1; J=$2; ST=${3:-2}; N=$(basename $J); O=$W/a551/$V/$N; rm -rf $O; mkdir -p $O
  timeout 10800 $W/env/bin/python $W/maxrss.py "$N $V" $W/a551/rss.jsonl $W/env/bin/python -u $W/$V/sds2-step-pipeline/decode/sds2_to_step.py $J -o $O/${N}_stage$ST.step --stage $ST --verify > $O/convert.log 2>&1
  grep -av '^\*\|Transferr\|^\s*$\|\[0m\|\[32;1m' $O/convert.log > $O/${N}_stage$ST.log
  aws s3 cp --quiet --recursive $O $R/$V/$N/ --exclude "*.step" --exclude "convert.log"
}
export -f run
export W R
mkdir -p $W/a551
{
for id in 7699a4a7 b9c720b9 4e990883 bf938cf8 30ff95cd f0c2c894 3adae7db; do echo "v541 $W/jobs3/ev_$id 2"; echo "v551 $W/jobs3/ev_$id 2"; done
for J in $W/jobs/GMS $W/jobs/160920_AGNEWS* $W/jobs/AGNEWS_HS_Bldg-T* $W/jobs/TYSONS* $W/jobs/METHODIST*; do echo "v551 $J 2"; done
echo "v551 $W/jobs3/19002-IMS6_JOB_fb1cae 1"
} | xargs -P 6 -L 1 bash -c 'run "$0" "$1" "$2"'
aws s3 cp --quiet $W/a551/rss.jsonl $R/rss.jsonl
date -u +%FT%TZ > $W/A551_DONE; aws s3 cp --quiet $W/A551_DONE $R/A551_DONE
