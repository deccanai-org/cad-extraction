#!/bin/bash
# v5.5.9 on BOX-B: joist round trip (v558b vs v559a), calibration-failure jobs, control
W=/work/agentwork/sds2v54; cd $W
export AWS_DEFAULT_REGION=ap-south-1 PYTHONUNBUFFERED=1 MPLBACKEND=Agg OMP_NUM_THREADS=1
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/f559
C=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2v54
aws s3 cp --quiet $C/v559a.tgz $W/v559a.tgz; rm -rf $W/v559a; mkdir -p $W/v559a && tar xzf $W/v559a.tgz -C $W/v559a
until [ -f $W/stage_b.txt ]; do sleep 20; done
F=cad-disk-extract/zenitude-data-3/_state/conv/sds2/files
for id in 18e77755 7fa1c983 e1304b91 94b59c49 58c96961 6eeedc27 2ac238d7; do
  [ -d $W/jobs3/k_$id ] || { k=$(aws s3 ls s3://bim-proprietary-data/$F/$id | awk '{print $4}' | head -1); $W/env/bin/python $W/getjob3k.py $F/$k $W/jobs3 k_$id > /dev/null 2>&1; }
done
run() {
  V=$1; J=$2; ST=${3:-2}; N=$(basename $J); O=$W/f559/$V/$N; rm -rf $O; mkdir -p $O
  timeout 14400 $W/env/bin/python $W/maxrss.py "$N $V" $W/f559/rss.jsonl $W/env/bin/python -u $W/$V/sds2-step-pipeline/decode/sds2_to_step.py $J -o $O/${N}_stage$ST.step --stage $ST --verify > $O/convert.log 2>&1
  echo "rc=$?" >> $O/convert.log
  grep -av '^\*\|Transferr\|^\s*$\|\[0m\|\[32;1m' $O/convert.log > $O/${N}_stage$ST.log
  aws s3 cp --quiet --recursive $O $R/$V/$N/ --exclude "*.step" --exclude "convert.log"; rm -f $O/*.step
}
export -f run; export W R
mkdir -p $W/f559
{
for j in j_0535bdbb j_4c381a54; do echo "v559a $W/jobs3/$j 2"; echo "v558b $W/jobs3/$j 2"; done
for id in 18e77755 7fa1c983 e1304b91 94b59c49 58c96961 6eeedc27 2ac238d7; do echo "v559a $W/jobs3/k_$id 2"; done
for J in $W/jobs/METHODIST* $W/jobs/GMS $W/jobs/AGNEWS_HS_Bldg-T* $W/jobs/TYSONS* $W/jobs/160920_AGNEWS*; do echo "v559a $J 2"; done
echo "v559a $W/jobs3/19002-IMS6_JOB_fb1cae 1"
} | xargs -P 8 -L 1 bash -c 'run "$0" "$1" "$2"'
date -u +%FT%TZ > $W/F559_DONE; aws s3 cp --quiet $W/F559_DONE $R/F559_DONE
