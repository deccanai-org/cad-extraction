#!/bin/bash
exec > /var/log/pkg-boot.log 2>&1
dnf install -y python3-pip >/dev/null 2>&1; pip3 install -q boto3
SRC=ifc; FIRST=14; LAST=29; N=30
S=s3://annotationprod/cad-disk-extract/_control/packaging/step_v1_$SRC
mkdir -p /opt/pkg && cd /opt/pkg
aws s3 cp --region ap-south-1 --quiet $S/pkg_step.py /opt/pkg/pkg_step.py
for i in $(seq $FIRST $LAST); do
  (PKG_SOURCES=$SRC PKG_SHARD=$i/$N THREADS=48 PROJ_THREADS=1 nohup python3 /opt/pkg/pkg_step.py apply > /opt/pkg/shard_$i.log 2>&1 &)
done
while true; do for f in /opt/pkg/shard_*.log; do echo "== $f"; tail -3 $f; done > /opt/pkg/status.txt; aws s3 cp --region ap-south-1 --quiet /opt/pkg/status.txt $S/status_$(hostname).txt; sleep 60; done
