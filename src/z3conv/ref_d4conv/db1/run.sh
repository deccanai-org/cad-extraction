#!/bin/bash
# Zentitude-data-4 Tekla DB1 -> STEP fleet worker. Fresh AL2023 / Ubuntu x86_64 box with instance role cad-disk-extract-ec2.
#   aws s3 cp s3://annotationprod/cad-disk-extract/zentitude-data-4/_control/conv/ifc/run.sh /tmp/run.sh && bash /tmp/run.sh
# Blocks: builds the env (setup.sh), then loops the worker (re-synced from S3 each round = hot reload).
# Returns 0 only when the worker wrote $W/DONE.ifc (every job has a result, no hold flag).
# Env: CONV_HOME (/opt/conv), CONV_SCRATCH (work dir; default /scratch/conv if /scratch is mounted), CONV_SLOTS (default nproc/2).
PIPE=db1
export AWS_DEFAULT_REGION=ap-south-1
unset LD_LIBRARY_PATH
W=${CONV_HOME:-/opt/conv}; K=$W/kit/$PIPE; CTL=s3://annotationprod/cad-disk-extract/zentitude-data-4/_control/conv
mkdir -p "$W" "$K"
if [ -z "$CONV_SCRATCH" ]; then if mountpoint -q /scratch; then CONV_SCRATCH=/scratch/conv; else CONV_SCRATCH=$W/work; fi; fi
mkdir -p "$CONV_SCRATCH"
aws s3 cp --only-show-errors $CTL/$PIPE/setup.sh "$W/setup.sh"
for i in 1 2 3; do bash "$W/setup.sh" "$W" > "$W/setup.log" 2>&1 && break; sleep 30; done
tail -3 "$W/setup.log"
while true; do
  aws s3 sync --only-show-errors $CTL/$PIPE/ "$K/" --exclude "jobs.json" --exclude "*.md" --exclude "_*"
  if aws s3 ls $CTL/$PIPE/stop > /dev/null 2>&1; then echo "$(date -u +%FT%TZ) stop flag: pausing"; sleep 300; continue; fi
  CONV_HOME=$W CONV_WORK=$CONV_SCRATCH/$PIPE CONV_DONE=$W/DONE.$PIPE "$W/env/bin/python" "$K/worker.py" >> "$W/worker-$PIPE.log" 2>&1
  rc=$?
  echo "$(date -u +%FT%TZ) worker exit rc=$rc" >> "$W/worker-$PIPE.log"
  [ -f "$W/DONE.$PIPE" ] && exit 0
  sleep 20
done
