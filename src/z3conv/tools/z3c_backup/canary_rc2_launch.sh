#!/bin/bash
# SDS2 v5.5.11-rc4 canary (replaces rc3, NO-GO; file name kept for the permission rule): the same 15 jobs (canary_rc3_jobs.json)
# spread over 8 boxes (2 slots each, CONV_PRIORITY=1), claims shared. Stops this box's rc3 canary unit and its job processes first
# (two candidates must not re-run the same ids at once). Canary runs never replace the live production result (worker rule 00:05Z).
export AWS_DEFAULT_REGION=ap-south-1
CTL=s3://annotationprod/cad-disk-extract/_control/z3conv
PY=/opt/conv/sds2env/bin/python
[ -x $PY ] || { echo "$(hostname): no sds2env - skipped"; exit 0; }
if systemctl is-active -q z3canary-rc3 2>/dev/null; then
  systemctl stop z3canary-rc3; sleep 3; n=0
  for d in /proc/[0-9]*; do
    if tr '\0' '\n' < $d/environ 2>/dev/null | grep -q '^TMPDIR=/scratch/conv/canary_rc3/\|^TMPDIR=/opt/conv/work/canary_rc3/'; then kill ${d#/proc/} 2>/dev/null; n=$((n+1)); fi
  done
  echo "rc3 unit stopped, $n job processes ended"
fi
if mountpoint -q /scratch; then S=/scratch/conv; else S=/opt/conv/work; fi
C=/opt/conv/canary/rc4; mkdir -p $C/sds2 $S/canary_rc4
aws s3 sync --only-show-errors $CTL/test/sds2canary/rc4/ $C/sds2/
IDS=$(aws s3 cp --quiet $CTL/sds2/canary_rc3_jobs.json - | $PY -c "import json,sys; print(','.join(j['id'] for j in json.load(sys.stdin)))")
systemctl stop z3canary-rc4 2>/dev/null; systemctl reset-failed z3canary-rc4 2>/dev/null
systemd-run --unit=z3canary-rc4 --collect --working-directory=$C/sds2 --setenv=CONV_HOME=/opt/conv --setenv=CONV_WORK=$S/canary_rc4 \
  --setenv=CONV_DONE=$C/DONE --setenv=CONV_JOBS_KEY=ctl:canary_rc3_jobs.json --setenv=CONV_NO_EXTRA=1 --setenv=CONV_RERUN=$IDS \
  --setenv=CONV_RERUN_ONCE=1 --setenv=CONV_EXIT_WHEN_DONE=1 --setenv=CONV_SLOTS=2 --setenv=CONV_NO_RELOAD=1 --setenv=CLAIM_STALE_S=420 --setenv=CONV_PRIORITY=1 \
  --setenv=AWS_DEFAULT_REGION=ap-south-1 /bin/bash -c "$PY $C/sds2/worker.py >> $C/worker.log 2>&1"
sleep 40; echo "rc4 $(systemctl is-active z3canary-rc4) ids=$(echo $IDS | tr ',' '\n' | wc -l)"; tail -n 2 $C/worker.log | cut -c1-170; uptime
