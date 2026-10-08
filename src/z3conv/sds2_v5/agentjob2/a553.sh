#!/bin/bash
# v5.5.2 (stored bolt hardware) and v5.5.3 (reference models): before/after on evidence jobs + control regression
W=/work/agentwork/sds2v54
cd $W
export AWS_DEFAULT_REGION=ap-south-1 PYTHONUNBUFFERED=1 MPLBACKEND=Agg OMP_NUM_THREADS=1
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/a553
C=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2v54
for v in v552 v553; do aws s3 cp --quiet $C/$v.tgz $W/$v.tgz; rm -rf $W/$v; mkdir -p $W/$v && tar xzf $W/$v.tgz -C $W/$v; done
F=cad-disk-extract/zenitude-data-3/_state/conv/sds2/files
fetch() {
  k=$(aws s3 ls s3://bim-proprietary-data/$F/$1 | awk '{print $4}' | head -1)
  [ -d $W/jobs3/ev_$1 ] || $W/env/bin/python $W/getjob3k.py $F/$k $W/jobs3 ev_$1 > /dev/null 2>> $W/fetch3.err
}
for id in 11be3648 606dfec9 414b6e93 bbe1a0f2 1c5919db 23c10723 0965ed04 0e6cc241; do fetch $id; done
run() {
  V=$1; J=$2; ST=${3:-2}; N=$(basename $J); O=$W/a553/$V/$N; rm -rf $O; mkdir -p $O
  timeout 10800 $W/env/bin/python $W/maxrss.py "$N $V" $W/a553/rss.jsonl $W/env/bin/python -u $W/$V/sds2-step-pipeline/decode/sds2_to_step.py $J -o $O/${N}_stage$ST.step --stage $ST --verify > $O/convert.log 2>&1
  grep -av '^\*\|Transferr\|^\s*$\|\[0m\|\[32;1m' $O/convert.log > $O/${N}_stage$ST.log
  aws s3 cp --quiet --recursive $O $R/$V/$N/ --exclude "*.step" --exclude "convert.log"
}
export -f run
export W R
mkdir -p $W/a553
{
echo "v541 $W/jobs3/ev_11be3648 2"; echo "v552 $W/jobs3/ev_11be3648 2"
for id in 606dfec9 414b6e93 bbe1a0f2 23c10723 0965ed04 0e6cc241 1c5919db; do echo "v541 $W/jobs3/ev_$id 2"; echo "v553 $W/jobs3/ev_$id 2"; done
for J in $W/jobs/GMS $W/jobs/160920_AGNEWS* $W/jobs/AGNEWS_HS_Bldg-T* $W/jobs/TYSONS* $W/jobs/METHODIST*; do echo "v553 $J 2"; done
} | xargs -P 5 -L 1 bash -c 'run "$0" "$1" "$2"'
aws s3 cp --quiet $W/a553/rss.jsonl $R/rss.jsonl
date -u +%FT%TZ > $W/A553_DONE; aws s3 cp --quiet $W/A553_DONE $R/A553_DONE
