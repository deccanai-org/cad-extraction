#!/bin/bash
exec > /var/log/db1v2-boot.log 2>&1
dnf install -y python3-pip >/dev/null 2>&1; pip3 install -q boto3
mkdir -p /opt/db1v2 && cd /opt/db1v2
# restart loop: killing the worker restarts it with fresh code; only DONE (all jobs finished) ends the machine
while true; do
  aws s3 cp --region ap-south-1 --quiet s3://annotationprod/cad-disk-extract/_control/db1-v2/src/db1_worker.py /opt/db1v2/db1_worker.py
  DB1_SLOTS=$(( $(nproc) - 2 )) python3 /opt/db1v2/db1_worker.py >> /opt/db1v2/worker.out 2>&1
  [ -f /opt/db1v2/DONE ] && break
  sleep 20
done
aws s3 cp --region ap-south-1 /opt/db1v2/worker.out s3://annotationprod/cad-disk-extract/_state/db1-v2/logs/$(hostname).final.log
shutdown -h now
