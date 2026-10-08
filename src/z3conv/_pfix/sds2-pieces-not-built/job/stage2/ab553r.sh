#!/bin/bash
# ab553r.sh: final tree (v553r = v553q + 2g pieces kept out of the weight check + comments) on the 2g jobs, and the
# State_Reno reference time-budget job on v5.5.3 vs v553r
W=/work/agentwork/sds2-pieces-not-built; cd $W
export AWS_DEFAULT_REGION=ap-south-1
C=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-pieces-not-built
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-pieces-not-built/ab553
aws s3 cp --quiet $C/trees553r.tgz $W/stage/trees553r.tgz
rm -rf $W/trees/v553r && tar xzf $W/stage/trees553r.tgz -C $W/trees
SR=$(/opt/conv/env/bin/python $W/stage/fetch_one.py $W/jobs df6dfb4db0cbc70a15156664 16 State_Reno 2>>$W/out/ab553_fetch.err | tail -1)
run() {
  V=$1; J=$2; N=$(basename $J); O=$W/ab553/$V/$N
  [ -f $O/rc.txt ] && return
  rm -rf $O; mkdir -p $O
  while [ "$(awk '/MemAvailable/{print int($2/1048576)}' /proc/meminfo)" -lt 90 ]; do sleep 20; done
  export PYTHONUNBUFFERED=1 MPLBACKEND=Agg OMP_NUM_THREADS=1
  t0=$(date +%s)
  ( cd $O && timeout 14400 $W/env/bin/python -u $W/trees/$V/decode/sds2_to_step.py $J -o $O/${N}_stage2.step --stage 2 --verify > $O/convert.log 2>&1 )
  echo "rc=$? wall=$(( $(date +%s) - t0 ))" > $O/rc.txt
  grep -av '^\*\|Transferr\|^\s*$\|^\$ \|\[0m\|\[32;1m' $O/convert.log | tail -c 200000 > $O/${N}_stage2.log
  rm -f $O/${N}_stage2.step
  aws s3 cp --only-show-errors --recursive $O $R/$V/$N/ --exclude "convert.log" --exclude "*.png" --exclude "*.step"
}
export -f run; export W R
{ echo "v553r $W/jobs/$SR"; echo "v553 $W/jobs/$SR";
  for n in SHOAL_CREEK_BLDG-A_09OCT12_JOB_235d45 BAHA_HOT_7135_050613_Job_Roof_5_App.zip_d0ae3c STUART_BRADLEY_1368_JOB_582bbc RCMS_JOB_2dc764 A-Practice_Job_1cd870; do echo "v553r $W/jobs/$n"; done; } | xargs -P 4 -L 1 bash -c 'run "$0" "$1"'
date -u +%FT%TZ > $W/out/AB553R_DONE; aws s3 cp --quiet $W/out/AB553R_DONE $R/AB553R_DONE
