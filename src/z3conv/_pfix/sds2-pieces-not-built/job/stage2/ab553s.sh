#!/bin/bash
# ab553s.sh: the final patch tree (v553s) on the feature jobs and the class-1 controls
W=/work/agentwork/sds2-pieces-not-built; cd $W
export AWS_DEFAULT_REGION=ap-south-1
C=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-pieces-not-built
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-pieces-not-built/ab553
aws s3 cp --quiet $C/trees553s.tgz $W/stage/trees553s.tgz
rm -rf $W/trees/v553s && tar xzf $W/stage/trees553s.tgz -C $W/trees
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
{ for n in A-Practice_Job_1cd870 19156_610_WALNUT_JOB_09152020_7773ea STUART_BRADLEY_1368_JOB_582bbc RCMS_JOB_2dc764 THERMOFISHER_JOB_bff8f8 jfkf_23c107 KL_10c4a7 BAHA_HOT_7135_050613_Job_Roof_5_App.zip_d0ae3c RMC_JOB_4d1080 WHITE_CASTE_REV1_JOB_21b5d5 LANDMARK_CENTER_PHASE_3_03012023_JOB_affe42 profil1_a8ef94; do echo "v553s $W/jobs/$n"; done; } | xargs -P 4 -L 1 bash -c 'run "$0" "$1"'
date -u +%FT%TZ > $W/out/AB553S_DONE; aws s3 cp --quiet $W/out/AB553S_DONE $R/AB553S_DONE
