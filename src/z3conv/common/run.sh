#!/bin/bash
# Zenitude-data-3 conversion fleet worker loop (one per box per pipeline). PIPE is substituted per kit.
#   aws s3 cp s3://annotationprod/cad-disk-extract/_control/z3conv/PIPE/run.sh /opt/run.sh && bash /opt/run.sh
# Builds the env (setup.sh), then loops the worker (kit re-synced from S3 each round = hot reload).
# Returns 0 only when the worker wrote $W/DONE.$PIPE (every job has a result, no hold flag).
PIPE=__PIPE__
export AWS_DEFAULT_REGION=ap-south-1
unset LD_LIBRARY_PATH
W=${CONV_HOME:-/opt/conv}; K=$W/kit/$PIPE; CTL=s3://annotationprod/cad-disk-extract/_control/z3conv
ST=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/conv/$PIPE
mkdir -p "$W" "$K"
if [ -z "$CONV_SCRATCH" ]; then if mountpoint -q /scratch; then CONV_SCRATCH=/scratch/conv; else CONV_SCRATCH=$W/work; fi; fi
mkdir -p "$CONV_SCRATCH"
# safe kit sync: download into a staging dir, copy only non-empty files (an empty object on S3 never replaces a good local file)
sync_kit() {
  mkdir -p "$K.stage"
  aws s3 sync --only-show-errors $CTL/$PIPE/ "$K.stage/" --exclude '*' --include '*.py' --include '*.sh' --include '*.json' --include '*.zip' --include '*.txt' --exclude '*/*'
  for f in "$K.stage"/*; do
    [ -f "$f" ] || continue; b=$(basename "$f")
    if [ -s "$f" ]; then cmp -s "$f" "$K/$b" || cp -p "$f" "$K/$b"
    else echo "$(date -u +%FT%TZ) WARNING: $b is empty on S3: kept the local copy" >> "$W/worker-$PIPE.log"; fi
  done
}
# python for the worker: pybin.txt when it names an executable; else the last good value; else the known default
pyb() {
  c=""; [ -s "$K/pybin.txt" ] && c="$W/$(head -c 200 "$K/pybin.txt" | tr -d '\r\n ')"
  if [ -n "$c" ] && [ -f "$c" ] && [ -x "$c" ]; then echo "$c" > "$W/.pybin.last.$PIPE"; echo "$c"; return; fi
  [ -n "$c" ] && echo "$(date -u +%FT%TZ) WARNING: pybin.txt names no executable ($c): fallback" >> "$W/worker-$PIPE.log"
  if [ -s "$W/.pybin.last.$PIPE" ] && [ -x "$(cat "$W/.pybin.last.$PIPE")" ]; then cat "$W/.pybin.last.$PIPE"
  elif [ "$PIPE" = sds2 ] && [ -x "$W/sds2env/bin/python" ]; then echo "$W/sds2env/bin/python"
  else echo "$W/env/bin/python"; fi
}
flag() { aws s3api head-object --bucket "$(echo $1 | cut -d/ -f3)" --key "$(echo $1 | cut -d/ -f4-)" > /dev/null 2>&1; }   # exact key, never a prefix match
released() { flag $CTL/$PIPE/release || flag $CTL/release; }
sync_kit
PYBIN=$W/env/bin/python
for i in 1 2 3; do bash "$K/setup.sh" "$W" "$K" > "$W/setup-$PIPE.log" 2>&1 && break; sleep 30; done
tail -3 "$W/setup-$PIPE.log"
PYBIN=$(pyb)
aws s3 cp --quiet "$W/setup-$PIPE.log" $ST/boot/$(hostname).setup.log
while true; do
  sync_kit
  if released; then echo "$(date -u +%FT%TZ) release flag: exiting (box powers off)"; touch "$W/RELEASED.$PIPE"; exit 0; fi
  if flag $CTL/$PIPE/stop || flag $CTL/stop; then echo "$(date -u +%FT%TZ) stop flag: pausing"; sleep 300; continue; fi
  PYBIN=$(pyb)
  CONV_HOME=$W CONV_WORK=$CONV_SCRATCH/$PIPE CONV_DONE=$W/DONE.$PIPE "$PYBIN" "$K/worker.py" >> "$W/worker-$PIPE.log" 2>&1
  rc=$?
  echo "$(date -u +%FT%TZ) worker exit rc=$rc" >> "$W/worker-$PIPE.log"
  aws s3 cp --quiet "$W/worker-$PIPE.log" $ST/boxlogs/$(hostname).log
  [ -f "$W/DONE.$PIPE" ] && exit 0
  sleep 20
done
