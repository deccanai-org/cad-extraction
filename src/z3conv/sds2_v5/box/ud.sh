#!/bin/bash
# cad-z3conv-sds2fix: v4-vs-v5 regression box. Self-terminates: watchdog shutdown after 7 h (instance-initiated
# shutdown = terminate); the driver also runs `shutdown -h now` when the regression is finished.
exec > /var/log/v5-boot.log 2>&1
set -x
shutdown -h +420 "sds2fix watchdog"
export AWS_DEFAULT_REGION=ap-south-1
dnf install -y -q tar gzip xz unzip p7zip p7zip-plugins > /dev/null 2>&1 || dnf install -y -q tar gzip xz unzip > /dev/null 2>&1
W=/opt/conv; K=$W/kit/sds2; mkdir -p $K /data
CTL=s3://annotationprod/cad-disk-extract/zentitude-data-4/_control/conv/sds2
for f in setup.sh sds2-step-pipeline-v4-candidate.zip fetch.py convfleet.py worker.py jobs.json; do
  for i in 1 2 3 4 5; do aws s3 cp --only-show-errors $CTL/$f $K/$f && break; sleep 10; done
done
for i in 1 2 3; do bash $K/setup.sh $W $K > $W/setup.log 2>&1 && break; sleep 30; done
tail -3 $W/setup.log
$W/sds2env/bin/pip install -q ifcopenshell > $W/pip-extra.log 2>&1 || true
date -u +%FT%TZ > $W/SETUP_DONE
aws s3 cp $W/setup.log s3://annotationprod/cad-disk-extract/_control/z3conv/sds2/v5dev/boot/setup.log || true
