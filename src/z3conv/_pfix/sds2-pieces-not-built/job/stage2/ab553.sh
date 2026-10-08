#!/bin/bash
# ab553.sh: v5.5.3 (v553) vs v5.5.3 + this patch (v553q) on the A/B job set, fleet command (--stage 2 --verify)
W=/work/agentwork/sds2-pieces-not-built; cd $W
export AWS_DEFAULT_REGION=ap-south-1
C=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-pieces-not-built
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-pieces-not-built/ab553
for f in ab553_ids.txt trees553q.tgz trees553.tgz fetch_one.py fetch.py; do aws s3 cp --quiet $C/$f $W/stage/$f; done
[ -d $W/trees/v553 ] || tar xzf $W/stage/trees553.tgz -C $W/trees v553
rm -rf $W/trees/v553q && tar xzf $W/stage/trees553q.tgz -C $W/trees
mkdir -p $W/ab553 $W/out
: > $W/out/ab553_dirs.txt
while read id nm; do /opt/conv/env/bin/python $W/stage/fetch_one.py $W/jobs $id 16 $nm 2>>$W/out/ab553_fetch.err | tail -1 >> $W/out/ab553_dirs.txt; done < $W/stage/ab553_ids.txt
run() {
  V=$1; J=$2; N=$(basename $J); O=$W/ab553/$V/$N
  [ -f $O/rc.txt ] && return
  rm -rf $O; mkdir -p $O
  while [ "$(awk '/MemAvailable/{print int($2/1048576)}' /proc/meminfo)" -lt 90 ]; do sleep 20; done
  export PYTHONUNBUFFERED=1 MPLBACKEND=Agg OMP_NUM_THREADS=1
  t0=$(date +%s)
  ( cd $O && timeout 10800 $W/env/bin/python -u $W/trees/$V/decode/sds2_to_step.py $J -o $O/${N}_stage2.step --stage 2 --verify > $O/convert.log 2>&1 )
  echo "rc=$? wall=$(( $(date +%s) - t0 ))" > $O/rc.txt
  grep -av '^\*\|Transferr\|^\s*$\|^\$ \|\[0m\|\[32;1m' $O/convert.log | tail -c 200000 > $O/${N}_stage2.log
  rm -f $O/${N}_stage2.step
  aws s3 cp --only-show-errors --recursive $O $R/$V/$N/ --exclude "convert.log" --exclude "*.png" --exclude "*.step"
}
export -f run; export W R
for n in $(cat $W/out/ab553_dirs.txt); do [ -n "$n" ] && { echo "v553q $W/jobs/$n"; echo "v553 $W/jobs/$n"; }; done > $W/out/ab553_queue.txt
cat $W/out/ab553_queue.txt | xargs -P ${PAR:-8} -L 1 bash -c 'run "$0" "$1"'
date -u +%FT%TZ > $W/out/AB553_DONE; aws s3 cp --quiet $W/out/AB553_DONE $R/AB553_DONE
