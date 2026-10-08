#!/bin/bash
W=/work/agentwork/sds2v54
mkdir -p $W
cd $W
aws s3 cp --quiet --recursive s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2v54/ .
chmod +x *.sh
setsid nohup bash $W/drive.sh > /dev/null 2>&1 < /dev/null &
disown
sleep 2
echo started
ls $W
