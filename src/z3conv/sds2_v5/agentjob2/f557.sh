#!/bin/bash
# v5.5.7 (rod / turned-piece sanity): control vs f556 v556b; rod / stud jobs v556b (before) vs v557d (after)
W=/work/agentwork/sds2v54; cd $W
export AWS_DEFAULT_REGION=ap-south-1 PYTHONUNBUFFERED=1 MPLBACKEND=Agg OMP_NUM_THREADS=1
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/f557
C=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2v54
aws s3 cp --quiet $C/v557d.tgz $W/v557d.tgz; rm -rf $W/v557d; mkdir -p $W/v557d && tar xzf $W/v557d.tgz -C $W/v557d
F=cad-disk-extract/zenitude-data-3/_state/conv/sds2/files
for id in ebce209f 866f2a7a ad00a536 a910dce4; do
  [ -d $W/jobs3/rb_$id ] || { k=$(aws s3 ls s3://bim-proprietary-data/$F/$id | awk '{print $4}' | head -1); $W/env/bin/python $W/getjob3k.py $F/$k $W/jobs3 rb_$id > /dev/null 2>&1; }
done
run() {
  V=$1; J=$2; ST=${3:-2}; N=$(basename $J); O=$W/f557/$V/$N; rm -rf $O; mkdir -p $O
  timeout 10800 $W/env/bin/python $W/maxrss.py "$N $V" $W/f557/rss.jsonl $W/env/bin/python -u $W/$V/sds2-step-pipeline/decode/sds2_to_step.py $J -o $O/${N}_stage$ST.step --stage $ST --verify > $O/convert.log 2>&1
  grep -av '^\*\|Transferr\|^\s*$\|\[0m\|\[32;1m' $O/convert.log > $O/${N}_stage$ST.log
  aws s3 cp --quiet --recursive $O $R/$V/$N/ --exclude "*.step" --exclude "convert.log"; rm -f $O/*.step
}
export -f run; export W R
mkdir -p $W/f557
{
for id in ebce209f 866f2a7a ad00a536 a910dce4; do echo "v557d $W/jobs3/rb_$id 2"; echo "v556b $W/jobs3/rb_$id 2"; done
for J in $W/jobs/METHODIST* $W/jobs/GMS $W/jobs/AGNEWS_HS_Bldg-T* $W/jobs/TYSONS* $W/jobs/160920_AGNEWS*; do echo "v557d $J 2"; done
echo "v557d $W/jobs3/19002-IMS6_JOB_fb1cae 1"
[ -d $W/jobs3/p_bdf8059f ] && echo "v557d $W/jobs3/p_bdf8059f 2"
echo "v557d $W/jobs3/t_319570f4 2"; echo "v557d $W/jobs3/t_9ab5fb14 2"
} | xargs -P 6 -L 1 bash -c 'run "$0" "$1" "$2"'
J=$(ls -d $W/jobs/160920_AGNEWS*); N=$(basename $J); O=$W/f557/v557d_budget/$N; mkdir -p $O
SDS2_VERIFY_BUDGET_S=15 timeout 3600 $W/env/bin/python -u $W/v557d/sds2-step-pipeline/decode/sds2_to_step.py $J -o $O/${N}_stage2.step --stage 2 --verify > $O/convert.log 2>&1
grep -av '^\*\|Transferr\|^\s*$\|\[0m\|\[32;1m' $O/convert.log > $O/${N}_stage2.log; aws s3 cp --quiet --recursive $O $R/v557d_budget/$N/ --exclude "*.step" --exclude "convert.log"
date -u +%FT%TZ > $W/F557_DONE; aws s3 cp --quiet $W/F557_DONE $R/F557_DONE
