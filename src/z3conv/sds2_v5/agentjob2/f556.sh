#!/bin/bash
# v5.5.6 (v5.5.5 + grating / rods patch): control vs f554 v554g, grating / rod jobs before (v555a) / after (v556b)
W=/work/agentwork/sds2v54; cd $W
export AWS_DEFAULT_REGION=ap-south-1 PYTHONUNBUFFERED=1 MPLBACKEND=Agg OMP_NUM_THREADS=1
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/f556
C=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2v54
aws s3 cp --quiet $C/v556b.tgz $W/v556b.tgz; rm -rf $W/v556b; mkdir -p $W/v556b && tar xzf $W/v556b.tgz -C $W/v556b
[ -d $W/v555a ] || { aws s3 cp --quiet $C/v555a.tgz $W/v555a.tgz; mkdir -p $W/v555a && tar xzf $W/v555a.tgz -C $W/v555a; }
F=cad-disk-extract/zenitude-data-3/_state/conv/sds2/files
for id in 096e7f88 3adae7db 4e990883; do
  [ -d $W/jobs3/ev_$id ] || { k=$(aws s3 ls s3://bim-proprietary-data/$F/$id | awk '{print $4}' | head -1); $W/env/bin/python $W/getjob3k.py $F/$k $W/jobs3 ev_$id > /dev/null 2>&1; }
done
run() {
  V=$1; J=$2; ST=${3:-2}; N=$(basename $J); O=$W/f556/$V/$N; rm -rf $O; mkdir -p $O
  timeout 14400 $W/env/bin/python $W/maxrss.py "$N $V" $W/f556/rss.jsonl $W/env/bin/python -u $W/$V/sds2-step-pipeline/decode/sds2_to_step.py $J -o $O/${N}_stage$ST.step --stage $ST --verify > $O/convert.log 2>&1
  grep -av '^\*\|Transferr\|^\s*$\|\[0m\|\[32;1m' $O/convert.log > $O/${N}_stage$ST.log
  aws s3 cp --quiet --recursive $O $R/$V/$N/ --exclude "*.step" --exclude "convert.log"
  rm -f $O/*.step
}
export -f run
export W R
mkdir -p $W/f556
{
echo "v556b $W/jobs3/ev_096e7f88 2"; echo "v555a $W/jobs3/ev_096e7f88 2"
for J in $W/jobs/METHODIST* $W/jobs/GMS $W/jobs/AGNEWS_HS_Bldg-T* $W/jobs/TYSONS* $W/jobs/160920_AGNEWS*; do echo "v556b $J 2"; done
echo "v556b $W/jobs3/19002-IMS6_JOB_fb1cae 1"
for id in 5ce1bf4b 859650c1 9ab5fb14; do echo "v556b $W/jobs3/t_$id 2"; done
for id in 3adae7db 4e990883; do echo "v556b $W/jobs3/ev_$id 2"; echo "v555a $W/jobs3/ev_$id 2"; done
} | xargs -P 7 -L 1 bash -c 'run "$0" "$1" "$2"'
aws s3 cp --quiet $W/f556/rss.jsonl $R/rss.jsonl
date -u +%FT%TZ > $W/F556_DONE; aws s3 cp --quiet $W/F556_DONE $R/F556_DONE
