#!/bin/bash
exec > /var/log/pkg-boot.log 2>&1
dnf install -y python3-pip >/dev/null 2>&1; pip3 install -q boto3
mkdir -p /opt/pkg && cd /opt/pkg
S=s3://annotationprod/cad-disk-extract/_control/packaging/step_v1_ifc
aws s3 cp --region ap-south-1 --quiet $S/pkg_step.py /opt/pkg/pkg_step.py
( while true; do aws s3 cp --region ap-south-1 --quiet /opt/pkg/apply.log $S/apply.log; sleep 60; done ) &
# apply is idempotent (per-project done markers): retry until clean
for i in 1 2 3 4 5; do
  PKG_SOURCES=ifc THREADS=96 PROJ_THREADS=12 python3 /opt/pkg/pkg_step.py apply >> /opt/pkg/apply.log 2>&1 && break
  sleep 60
done
aws s3 cp --region ap-south-1 --quiet /opt/pkg/apply.log $S/apply.final.log
shutdown -h now
