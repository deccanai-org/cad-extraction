#!/bin/bash
# Data-4 packaging APPLY on the coordinator (owner-approved activation 10-04 02:07Z; fleet package workers read only the data-3 job list).
# Runs every job in bim _state/conv/package/jobs_zen4.json with the deployed packager (pkg h), 16 at a time; writes only
# dataset/packages/3d/Zentitude-data-4__*/ and _state/packaging/ records (the packager never deletes). Idempotent: done jobs skip.
export AWS_DEFAULT_REGION=ap-south-1
PY=/opt/conv/env/bin/python; D=/opt/pkgd4; mkdir -p $D/jobs $D/work $D/logs
if systemctl is-active -q z3pkg-d4apply; then echo "running since $(cat $D/started)"; echo "ok=$(grep -l '"status": "ok"' $D/logs/*.log 2>/dev/null | wc -l) logs=$(ls $D/logs | wc -l) of $(ls $D/jobs | wc -l)"; exit 0; fi
if [ -f $D/finished ]; then echo "finished $(cat $D/finished)"; echo "ok=$(grep -l '"status": "ok"' $D/logs/*.log 2>/dev/null | wc -l) of $(ls $D/jobs | wc -l)"; grep -L '"status": "ok"' $D/logs/*.log | head -5; exit 0; fi
aws s3 sync --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/package/ $D/kit/ --exclude '*/*'
aws s3 cp --quiet s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/conv/package/jobs_zen4.json $D/jobs_zen4.json
$PY -c "
import json; d=json.load(open('$D/jobs_zen4.json'))
for j in d['jobs']: json.dump(j, open('$D/jobs/'+j['id']+'.json','w'))
print('jobs', len(d['jobs']))"
date -u +%FT%TZ > $D/started
systemctl reset-failed z3pkg-d4apply 2>/dev/null
systemd-run --unit=z3pkg-d4apply --collect --nice=5 --working-directory=$D/kit --setenv=AWS_DEFAULT_REGION=ap-south-1 --setenv=PKG_ALLOW_WRITE=1 /bin/bash -c \
  "ls $D/jobs/*.json | xargs -P 16 -I{} sh -c 'b=\$(basename {} .json); $PY pkg.py job --job {} --workdir $D/work/\$b > $D/logs/\$b.log 2>&1; rm -rf $D/work/\$b'; date -u +%FT%TZ > $D/finished"
sleep 90; echo "logs=$(ls $D/logs | wc -l) ok=$(grep -l '"status": "ok"' $D/logs/*.log 2>/dev/null | wc -l)"; tail -n 3 $(ls -t $D/logs/*.log | head -1)
