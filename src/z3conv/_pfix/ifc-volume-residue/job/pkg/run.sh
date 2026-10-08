#!/bin/bash
# SSM launcher: sync the package, start the dev3 batch detached
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-volume-residue; mkdir -p $W/pkg && cd $W
aws s3 sync --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-volume-residue/ $W/pkg/
chmod +x $W/pkg/*.sh
setsid nohup bash $W/pkg/batch.sh dev3 $W/pkg/ifc2step6_dev3.py --jobs 4 > $W/batch_dev3.out 2>&1 < /dev/null &
echo started pid $!
sleep 5; ps -eo pid,args | grep -v grep | grep ifc-volume-residue | head; ls $W/pkg $W/pkg/kit $W/pkg/coord
