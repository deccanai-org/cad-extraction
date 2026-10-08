#!/bin/bash
# on the coordinator box: sync code, set up venv, run jobs file $1 with $2 processes in background, sync results every 2 min
SLUG=db1v2-eng; W=/work/agentwork/$SLUG; JOBS=${1:-jobs.json}; NP=${2:-12}
mkdir -p $W; cd $W
OUTP=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/$SLUG
case "$OUTP/" in s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/db1v2-eng/*) echo "S3 write destination: $OUTP (own prefix)";; *) echo "REFUSING: $OUTP is not under the agent prefix"; exit 1;; esac
aws s3 sync --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/$SLUG/ $W/ --exclude 'data/*' --exclude 'out/*' --exclude 'venv/*'
if [ ! -x $W/venv/bin/python ] || ! $W/venv/bin/python -c "import ifcopenshell, numpy" 2>/dev/null; then
  python3 -m venv $W/venv && $W/venv/bin/pip install -q --upgrade pip > /dev/null 2>&1; $W/venv/bin/pip install -q numpy "ifcopenshell==0.8.4.post1" boto3 lark > $W/pip.log 2>&1
fi
$W/venv/bin/python -c "import ifcopenshell, numpy; print('env', ifcopenshell.version, numpy.__version__)"
TAG=$(basename $JOBS .json)
setsid nohup bash -c "cd $W; ./venv/bin/python boxdrive.py $JOBS $NP > drive_$TAG.log 2>&1" > /dev/null 2>&1 &
setsid nohup bash -c "while true; do aws s3 sync --only-show-errors $W/out/ $OUTP/out/; aws s3 cp --quiet $W/drive_$TAG.log $OUTP/drive_$TAG.log; grep -q ALLDONE $W/drive_$TAG.log 2>/dev/null && break; sleep 120; done" > /dev/null 2>&1 &
echo launched $TAG
