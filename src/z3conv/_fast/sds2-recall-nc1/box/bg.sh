#!/bin/bash
# bg.sh NAME CMD... : run CMD detached on the box, log to $W/logs/NAME.log, mirror the log to S3 every 60 s
W=/work/agentwork/sds2-recall-nc1
RES=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-recall-nc1
N=$1; shift
mkdir -p $W/logs
cd $W
( "$@" > $W/logs/$N.log 2>&1; echo "EXIT $?" >> $W/logs/$N.log; aws s3 cp --quiet $W/logs/$N.log $RES/logs/$N.log ) &
P=$!
echo $P > $W/logs/$N.pid
while kill -0 $P 2>/dev/null; do aws s3 cp --quiet $W/logs/$N.log $RES/logs/$N.log; sleep 60; done
aws s3 cp --quiet $W/logs/$N.log $RES/logs/$N.log
