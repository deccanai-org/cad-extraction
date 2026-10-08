#!/bin/bash
exec > /var/log/ifc-boot.log 2>&1
dnf install -y python3-pip >/dev/null 2>&1
pip3 install -q boto3
mkdir -p /opt/ifc-step && cd /opt/ifc-step
aws s3 cp --region ap-south-1 s3://annotationprod/cad-disk-extract/_control/ifc-step/ifc_worker.py .
export IFC_ORDER=big IFC_SLOTS=3
python3 ifc_worker.py > worker.out 2>&1
aws s3 cp --region ap-south-1 worker.out s3://annotationprod/cad-disk-extract/_state/ifc-step/logs/$(hostname).final.log
shutdown -h now
