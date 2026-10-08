#!/bin/bash
# v5.5.8 regression: control (v558b vs f557 v557d / v557h), evidence before (v557h) / after (v558b)
W=/work/agentwork/sds2v54; cd $W
export AWS_DEFAULT_REGION=ap-south-1 PYTHONUNBUFFERED=1 MPLBACKEND=Agg OMP_NUM_THREADS=1
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/f558
C=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2v54
aws s3 cp --quiet $C/v558b.tgz $W/v558b.tgz; rm -rf $W/v558b; mkdir -p $W/v558b && tar xzf $W/v558b.tgz -C $W/v558b
[ -d $W/v557h ] || { aws s3 cp --quiet $C/v557h.tgz $W/v557h.tgz; mkdir -p $W/v557h && tar xzf $W/v557h.tgz -C $W/v557h; }
F=cad-disk-extract/zenitude-data-3/_state/conv/sds2/files
for id in ef345b81 8566eef0 1f2578ca 4a955413 c5f1d1d0; do
  [ -d $W/jobs3/e8_$id ] || { k=$(aws s3 ls s3://bim-proprietary-data/$F/$id | awk '{print $4}' | head -1); $W/env/bin/python $W/getjob3k.py $F/$k $W/jobs3 e8_$id > /dev/null 2>&1; }
done
run() {
  V=$1; J=$2; ST=${3:-2}; N=$(basename $J); O=$W/f558/$V/$N; rm -rf $O; mkdir -p $O
  timeout 14400 $W/env/bin/python $W/maxrss.py "$N $V" $W/f558/rss.jsonl $W/env/bin/python -u $W/$V/sds2-step-pipeline/decode/sds2_to_step.py $J -o $O/${N}_stage$ST.step --stage $ST --verify > $O/convert.log 2>&1
  grep -av '^\*\|Transferr\|^\s*$\|\[0m\|\[32;1m' $O/convert.log > $O/${N}_stage$ST.log
  aws s3 cp --quiet --recursive $O $R/$V/$N/ --exclude "*.step" --exclude "convert.log"; rm -f $O/*.step
}
export -f run; export W R
mkdir -p $W/f558
{
for id in ef345b81 8566eef0 1f2578ca 4a955413 c5f1d1d0; do echo "v558b $W/jobs3/e8_$id 2"; echo "v557h $W/jobs3/e8_$id 2"; done
echo "v558b $W/jobs3/t_319570f4 2"
for J in $W/jobs/METHODIST* $W/jobs/GMS $W/jobs/AGNEWS_HS_Bldg-T* $W/jobs/TYSONS* $W/jobs/160920_AGNEWS*; do echo "v558b $J 2"; done
echo "v558b $W/jobs3/19002-IMS6_JOB_fb1cae 1"
} | xargs -P 7 -L 1 bash -c 'run "$0" "$1" "$2"'
aws s3 cp --quiet $W/f558/rss.jsonl $R/rss.jsonl
date -u +%FT%TZ > $W/F558B_DONE; aws s3 cp --quiet $W/F558B_DONE $R/F558B_DONE
