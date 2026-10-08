#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue
# stop my ppv drive and all its descendants
D=$(pgrep -f "drive.py ppv_dev3")
desc() { for c in $(pgrep -P $1); do desc $c; echo $c; done; }
for p in $D; do for c in $(desc $p); do kill -9 $c 2>/dev/null; done; kill -9 $p 2>/dev/null; done
sleep 2
pgrep -af "ppv_dev3" | cut -c1-150
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/rc.py $W/job/rc.py
rm -rf $W/w/ppv_dev3/beeeacea7d2d7546 $W/w/ppv_dev3/1c61df42e5270bac $W/w/ppv_dev3/2bcaa3013d924a3a 2>/dev/null
ls $W/w/ppv_dev3/
free -g | head -2
