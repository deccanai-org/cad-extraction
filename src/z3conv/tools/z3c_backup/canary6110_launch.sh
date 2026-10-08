#!/bin/bash
# IFC 6.1.10-rc canary (lead 00:45Z; file name kept for the permission rule): one job per model, spread over every box; two units:
#   z3canary-ifc6110rc  = 6.1.10-rc (code ...+s6.1.10-rc, files <id>.v6110-rc.*)
#   z3canary-ifc6110ctl = 6.1.9 ctl  (code ...+s6.1.9-ctl, files <id>.v619-ctl.*)
# canary switches (own job list, once per id, exit when done, no reload, host priority); claims shared across boxes; canary runs never
# replace the live production result (worker rule 00:05Z)
export AWS_DEFAULT_REGION=ap-south-1
CTL=s3://annotationprod/cad-disk-extract/_control/z3conv
PY=/opt/conv/env/bin/python
[ -x $PY ] || { echo "$(hostname): no IFC env - skipped"; exit 0; }
$PY -c "import shapely" 2>/dev/null || $PY -m pip install -q shapely==2.1.2 > /opt/conv/shapely.log 2>&1 || echo "WARN: shapely not installed"
$PY -c "import shapely; print('shapely', shapely.__version__)" 2>&1 | tail -1
if mountpoint -q /scratch; then S=/scratch/conv; else S=/opt/conv/work; fi
SLOTS=${SLOTS:-$([ "$(nproc)" -le 32 ] && echo 2 || echo 3)}    # 32-vCPU boxes: 2 slots per unit
IDS=$(aws s3 cp --quiet $CTL/ifc/canary6110_jobs.json - | $PY -c "import json,sys; d=json.load(sys.stdin); d=d['jobs'] if isinstance(d,dict) else d; print(','.join(j['id'] for j in d))")
echo "ids: $(echo $IDS | tr ',' '\n' | wc -l)"
for L in rc ctl; do
  C=/opt/conv/canary/ifc6110$L; mkdir -p $C/ifc $S/canary_ifc6110$L
  aws s3 sync --only-show-errors $CTL/test/ifc6110/$L/ $C/ifc/ --exclude '*/*'
  systemctl stop z3canary-ifc6110$L 2>/dev/null; systemctl reset-failed z3canary-ifc6110$L 2>/dev/null
  TAG=""; [ $L = ctl ] && TAG="--setenv=IFC_CODE_TAG=ctl"
  systemd-run --unit=z3canary-ifc6110$L --collect --working-directory=$C/ifc --setenv=CONV_HOME=/opt/conv --setenv=CONV_WORK=$S/canary_ifc6110$L \
    --setenv=CONV_DONE=$C/DONE --setenv=CONV_JOBS_KEY=ctl:canary6110_jobs.json --setenv=CONV_NO_EXTRA=1 --setenv=CONV_RERUN=$IDS \
    --setenv=CONV_RERUN_ONCE=1 --setenv=CONV_EXIT_WHEN_DONE=1 --setenv=CONV_SLOTS=$SLOTS --setenv=CONV_NO_RELOAD=1 \
    --setenv=CONV_PRIORITY=1 --setenv=AWS_DEFAULT_REGION=ap-south-1 $TAG /bin/bash -c "$PY $C/ifc/worker.py >> $C/worker.log 2>&1"
done
sleep 40
for L in rc ctl; do echo "$L $(systemctl is-active z3canary-ifc6110$L) | $(grep -c ' ok ' /opt/conv/canary/ifc6110$L/worker.log 2>/dev/null) ok"; tail -n 2 /opt/conv/canary/ifc6110$L/worker.log | cut -c1-170; done
uptime
