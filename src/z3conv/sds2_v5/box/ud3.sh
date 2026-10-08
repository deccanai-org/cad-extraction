#!/bin/bash
# cad-z3conv-sds2fix-3: autonomous v4-vs-v5 regression. Self-terminates: `shutdown -h now` at the end of drive3.sh,
# watchdog shutdown after 5 h (instance-initiated shutdown = terminate).
exec > /var/log/v5-boot.log 2>&1
set -x
shutdown -h +300 "sds2fix watchdog"
export AWS_DEFAULT_REGION=ap-south-1
dnf install -y -q tar gzip xz unzip p7zip p7zip-plugins > /dev/null 2>&1 || dnf install -y -q tar gzip xz unzip > /dev/null 2>&1
W=/opt/conv; K=$W/kit/sds2; mkdir -p $K /data/out /opt/v5dev
CTL=s3://annotationprod/cad-disk-extract/zentitude-data-4/_control/conv/sds2
for f in setup.sh sds2-step-pipeline-v4-candidate.zip fetch.py convfleet.py worker.py jobs.json; do
  for i in 1 2 3 4 5; do aws s3 cp --only-show-errors $CTL/$f $K/$f && break; sleep 10; done
done
for i in 1 2 3; do bash $K/setup.sh $W $K > $W/setup.log 2>&1 && break; sleep 30; done
mkdir -p /opt/conv/v5 && cd /opt/conv/v5 && aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/sds2/v5dev/v5dev_r3.tgz v5.tgz && tar xzf v5.tgz
aws s3 cp --quiet --recursive s3://annotationprod/cad-disk-extract/_control/z3conv/sds2/v5dev/box3/ /opt/v5dev/
command -v 7za || dnf install -y -q p7zip > /dev/null 2>&1
bash /opt/v5dev/drive3.sh
