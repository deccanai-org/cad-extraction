#!/bin/bash
# pieces not built: v5.5.6 on the jobs with most no_usable_special_geometry (fleet before = their latest label)
W=/work/agentwork/sds2v54; cd $W
export AWS_DEFAULT_REGION=ap-south-1 PYTHONUNBUFFERED=1 MPLBACKEND=Agg OMP_NUM_THREADS=1
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/pnb
F=cad-disk-extract/zenitude-data-3/_state/conv/sds2/files
one() {
  id=$1; J=$W/jobs3/p_$id; O=$W/pnb/v556b/p_$id; rm -rf $O; mkdir -p $O
  [ -d $J ] || { k=$(aws s3 ls s3://bim-proprietary-data/$F/$id | awk '{print $4}' | head -1); $W/env/bin/python $W/getjob3k.py $F/$k $W/jobs3 p_$id > /dev/null 2>&1; }
  timeout 10800 $W/env/bin/python -u $W/v556b/sds2-step-pipeline/decode/sds2_to_step.py $J -o $O/p_${id}_stage2.step --stage 2 --verify > $O/convert.log 2>&1
  grep -av '^\*\|Transferr\|^\s*$\|\[0m\|\[32;1m' $O/convert.log > $O/p_${id}_stage2.log
  aws s3 cp --quiet --recursive $O $R/v556b/p_$id/ --exclude "*.step" --exclude "convert.log"; rm -f $O/*.step
}
export -f one; export W R F
echo 88926b20 bdf8059f df45224d 3b877893 9e1d7bf6 587e7d21 | tr ' ' '\n' | xargs -P 3 -I{} bash -c 'one {}'
date -u +%FT%TZ > $W/PNB_DONE; aws s3 cp --quiet $W/PNB_DONE $R/PNB_DONE
