#!/bin/bash
# Zenitude-data-3 conversion fleet worker loop (one per box per pipeline). PIPE is substituted per kit.
#   aws s3 cp s3://annotationprod/cad-disk-extract/_control/z3conv/PIPE/run.sh /opt/run.sh && bash /opt/run.sh
# Builds the env (setup.sh), then loops the worker (kit re-synced from S3 each round = hot reload).
# Returns 0 only when the worker wrote $W/DONE.$PIPE (every job has a result, no hold flag).
PIPE=sds2
export AWS_DEFAULT_REGION=ap-south-1
unset LD_LIBRARY_PATH
W=${CONV_HOME:-/opt/conv}; K=$W/kit/$PIPE; CTL=s3://annotationprod/cad-disk-extract/_control/z3conv
ST=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/conv/$PIPE
mkdir -p "$W" "$K"
if [ -z "$CONV_SCRATCH" ]; then if mountpoint -q /scratch; then CONV_SCRATCH=/scratch/conv; else CONV_SCRATCH=$W/work; fi; fi
mkdir -p "$CONV_SCRATCH"
sync_kit() { aws s3 sync --only-show-errors $CTL/$PIPE/ $K/ --exclude '*' --include '*.py' --include '*.sh' --include '*.json' --include '*.zip' --include '*.txt' --exclude '*/*'; }
released() { aws s3 ls $CTL/$PIPE/release > /dev/null 2>&1 || aws s3 ls $CTL/release > /dev/null 2>&1; }
sync_kit
PYBIN=$W/env/bin/python
for i in 1 2 3; do bash "$K/setup.sh" "$W" "$K" > "$W/setup-$PIPE.log" 2>&1 && break; sleep 30; done
tail -3 "$W/setup-$PIPE.log"
[ -f "$K/pybin.txt" ] && PYBIN=$W/$(cat $K/pybin.txt)
aws s3 cp --quiet "$W/setup-$PIPE.log" $ST/boot/$(hostname).setup.log
while true; do
  sync_kit
  if released; then echo "$(date -u +%FT%TZ) release flag: exiting (box powers off)"; touch "$W/RELEASED.$PIPE"; exit 0; fi
  if aws s3 ls $CTL/$PIPE/stop > /dev/null 2>&1 || aws s3 ls $CTL/stop > /dev/null 2>&1; then echo "$(date -u +%FT%TZ) stop flag: pausing"; sleep 300; continue; fi
  CONV_HOME=$W CONV_WORK=$CONV_SCRATCH/$PIPE CONV_DONE=$W/DONE.$PIPE "$PYBIN" "$K/worker.py" >> "$W/worker-$PIPE.log" 2>&1
  rc=$?
  echo "$(date -u +%FT%TZ) worker exit rc=$rc" >> "$W/worker-$PIPE.log"
  aws s3 cp --quiet "$W/worker-$PIPE.log" $ST/boxlogs/$(hostname).log
  [ -f "$W/DONE.$PIPE" ] && exit 0
  sleep 20
done
