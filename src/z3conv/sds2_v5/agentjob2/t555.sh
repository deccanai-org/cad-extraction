#!/bin/bash
W=/work/agentwork/sds2v54; cd $W; export AWS_DEFAULT_REGION=ap-south-1 PYTHONUNBUFFERED=1 MPLBACKEND=Agg OMP_NUM_THREADS=1
C=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2v54
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/t555
for f in v555a.tgz nomem_test.txt; do aws s3 cp --quiet $C/$f $W/$f; done
rm -rf $W/v555a; mkdir -p $W/v555a && tar xzf $W/v555a.tgz -C $W/v555a
F=cad-disk-extract/zenitude-data-3/_state/conv/sds2/files
one() {
  id=$1; J=$W/jobs_nm/z_${id:0:8}; O=$W/t555/z_${id:0:8}; rm -rf $O; mkdir -p $O
  k=$(aws s3 ls s3://bim-proprietary-data/$F/${id:0:8} | awk '{print $4}' | head -1)
  [ -d $J ] || $W/env/bin/python $W/getjob3k.py $F/$k $W/jobs_nm z_${id:0:8} > /dev/null 2>&1
  timeout 3600 $W/env/bin/python -u $W/v555a/sds2-step-pipeline/decode/sds2_to_step.py $J -o $O/z_stage2.step --stage 2 --verify > $O/convert.log 2>&1
  echo "rc=$?" >> $O/convert.log
  aws s3 cp --quiet --recursive $O $R/z_${id:0:8}/ --exclude "*.step"
  rm -rf $J
}
export -f one; export W R F
cat $W/nomem_test.txt | grep . | xargs -P 4 -I{} bash -c 'one {}'
O=$W/t555/agnewsr; mkdir -p $O; J=$(ls -d $W/jobs/160920_AGNEWS*); timeout 3600 $W/env/bin/python -u $W/v555a/sds2-step-pipeline/decode/sds2_to_step.py $J -o $O/a_stage2.step --stage 2 --verify > $O/convert.log 2>&1; aws s3 cp --quiet --recursive $O $R/agnewsr/ --exclude "*.step"
date -u +%FT%TZ > $W/T555_DONE; aws s3 cp --quiet $W/T555_DONE $R/T555_DONE
