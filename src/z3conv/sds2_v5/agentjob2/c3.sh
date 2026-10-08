#!/bin/bash
W=/work/agentwork/sds2v54; cd $W; export AWS_DEFAULT_REGION=ap-south-1 PYTHONUNBUFFERED=1 MPLBACKEND=Agg OMP_NUM_THREADS=1
C=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2v54
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/c3
aws s3 cp --quiet $C/c3_ids.txt $W/c3_ids.txt
F=cad-disk-extract/zenitude-data-3/_state/conv/sds2/files
one() {
  id=$1; g=$2; J=$W/jobs_c3/c_${id:0:8}; O=$W/c3/c_${id:0:8}; rm -rf $O; mkdir -p $O $W/jobs_c3
  k=$(aws s3 ls s3://bim-proprietary-data/$F/${id:0:8} | awk '{print $4}' | head -1)
  if [ -z "$k" ]; then echo "no files manifest" > $O/err.txt; aws s3 cp --quiet $O/err.txt $R/c_${id:0:8}/err.txt; return; fi
  [ -d $J ] || $W/env/bin/python $W/getjob3k.py $F/$k $W/jobs_c3 c_${id:0:8} > /dev/null 2>&1
  timeout 7200 $W/env/bin/python -u $W/v557b/sds2-step-pipeline/decode/sds2_to_step.py $J -o $O/c_stage2.step --stage 2 --verify > $O/convert.log 2>&1
  echo "rc=$? group=$g" >> $O/convert.log
  grep -av '^\*\|Transferr\|^\s*$\|\[0m\|\[32;1m' $O/convert.log | tail -300 > $O/c_stage2.log
  aws s3 cp --quiet --recursive $O $R/c_${id:0:8}/ --exclude "*.step" --exclude "convert.log" --exclude "*.png"
  rm -rf $J $O/*.step
}
export -f one; export W R F
cat $W/c3_ids.txt | grep . | xargs -P 4 -L 1 bash -c 'one $0 $1'
date -u +%FT%TZ > $W/C3_DONE; aws s3 cp --quiet $W/C3_DONE $R/C3_DONE
