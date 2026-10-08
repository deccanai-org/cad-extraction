#!/bin/bash
# review A/B: v553 vs v553p (v5.5.3 + sds2-pieces-not-built.diff), fleet command --stage 2 --verify
W=/work/agentwork/sds2-pieces-not-built-review; cd $W
export AWS_DEFAULT_REGION=ap-south-1
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-pieces-not-built-review/ab
PY=/work/agentwork/sds2-pieces-not-built/env/bin/python
mkdir -p $W/ab $W/out $W/jobs
: > $W/out/ab_dirs.txt
while read id nm; do /opt/conv/env/bin/python $W/stage/fetch_one.py $W/jobs $id 16 $nm 2>>$W/out/ab_fetch.err | tail -1 >> $W/out/ab_dirs.txt; done < $W/stage/ids.txt
aws s3 cp --quiet $W/out/ab_dirs.txt $R/ab_dirs.txt
run() {
  V=$1; J=$2; N=$(basename $J); O=$W/ab/$V/$N
  [ -f $O/rc.txt ] && return
  rm -rf $O; mkdir -p $O
  while [ "$(awk '/MemAvailable/{print int($2/1048576)}' /proc/meminfo)" -lt 100 ]; do sleep 20; done
  export PYTHONUNBUFFERED=1 MPLBACKEND=Agg OMP_NUM_THREADS=1
  t0=$(date +%s)
  ( cd $O && timeout 10800 $PY -u $W/trees/$V/decode/sds2_to_step.py $J -o $O/${N}_stage2.step --stage 2 --verify > $O/convert.log 2>&1 )
  echo "rc=$? wall=$(( $(date +%s) - t0 ))" > $O/rc.txt
  grep -av '^\*\|Transferr\|^\s*$\|^\$ \|\[0m\|\[32;1m' $O/convert.log | tail -c 200000 > $O/${N}_stage2.log
  rm -f $O/${N}_stage2.step
  aws s3 cp --only-show-errors --recursive $O $R/$V/$N/ --exclude "convert.log" --exclude "*.png" --exclude "*.step"
}
export -f run; export W R PY
for n in $(cat $W/out/ab_dirs.txt); do [ -n "$n" ] && { echo "v553p $W/jobs/$n"; echo "v553 $W/jobs/$n"; }; done > $W/out/ab_queue.txt
cat $W/out/ab_queue.txt | xargs -P ${PAR:-8} -L 1 bash -c 'run "$0" "$1"'
date -u +%FT%TZ > $W/out/AB_DONE; aws s3 cp --quiet $W/out/AB_DONE $R/AB_DONE
