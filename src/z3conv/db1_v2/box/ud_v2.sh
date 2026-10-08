#!/bin/bash
# cad-z3conv-db1v2 box: db1 v2 research/regression runner. Self-terminating (instance-initiated shutdown = terminate).
# Watchdogs: hard cap 16 h; idle (no task running, no new task) 120 min; S3 stop flag.
exec > /var/log/v2boot.log 2>&1
export AWS_DEFAULT_REGION=ap-south-1 HOME=/root
( sleep 57600; echo "hard cap"; shutdown -h now ) &
CTL=s3://annotationprod/cad-disk-extract/_control/z3conv/db1/v2/_box
OUT=s3://bim-proprietary-data/cad-disk-extract/_work/db1_v2
W=/opt/v2; mkdir -p $W/tasks $W/done $W/out; cd $W
dnf install -y -q python3-pip git > /dev/null 2>&1 || true
pip3 install -q boto3 numpy > /dev/null 2>&1 || true
aws s3 cp --quiet $CTL/box_loop.sh $W/box_loop.sh
bash $W/box_loop.sh
shutdown -h now
