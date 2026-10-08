#!/bin/bash
# the coordinator's 66 class-3 reference-like SDS2 jobs on v5.5.3 (stage 2, --verify); job dirs removed after each run
W=/work/agentwork/sds2v54
cd $W
export AWS_DEFAULT_REGION=ap-south-1 PYTHONUNBUFFERED=1 MPLBACKEND=Agg OMP_NUM_THREADS=1
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/r66
C=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2v54
aws s3 cp --quiet $C/ref66.txt $W/ref66.txt
F=cad-disk-extract/zenitude-data-3/_state/conv/sds2/files
one() {
  id=$1; V=v553b; J=$W/jobs66/r_$id; O=$W/r66/$V/r_$id
  [ -f $O/DONE ] && return
  rm -rf $O; mkdir -p $O $W/jobs66
  k=$(aws s3 ls s3://bim-proprietary-data/$F/$id | awk '{print $4}' | head -1)
  if [ -z "$k" ]; then echo "no files manifest" > $O/fetch.err; aws s3 cp --quiet $O/fetch.err $R/$V/r_$id/fetch.err; return; fi
  $W/env/bin/python $W/getjob3k.py $F/$k $W/jobs66 r_$id > /dev/null 2> $O/fetch.err
  timeout 10800 $W/env/bin/python $W/maxrss.py "r_$id $V" $W/r66/rss.jsonl $W/env/bin/python -u $W/$V/sds2-step-pipeline/decode/sds2_to_step.py $J -o $O/r_${id}_stage2.step --stage 2 --verify > $O/convert.log 2>&1
  echo "rc=$?" >> $O/convert.log
  grep -av '^\*\|Transferr\|^\s*$\|\[0m\|\[32;1m' $O/convert.log | tail -400 > $O/r_${id}_stage2.log
  aws s3 cp --quiet --recursive $O $R/$V/r_$id/ --exclude "*.step" --exclude "convert.log"
  rm -rf $J $O/*.step; touch $O/DONE
}
export -f one
export W R F
mkdir -p $W/r66
tr ' ' '\n' < $W/ref66.txt | grep . | xargs -P 4 -I{} bash -c 'one {}'
aws s3 cp --quiet $W/r66/rss.jsonl $R/rss.jsonl
date -u +%FT%TZ > $W/R66_DONE; aws s3 cp --quiet $W/R66_DONE $R/R66_DONE
