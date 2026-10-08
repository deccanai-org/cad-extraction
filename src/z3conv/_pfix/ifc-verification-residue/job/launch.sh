#!/bin/bash
# launch.sh LABEL TARGETS SLOTS THREADS VPROCS [extra drive args]
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue
cd $W
LABEL=$1; T=$2; S=$3; TH=$4; VP=$5; shift 5
CONVF=${CONVF:-ifc2step6_dev3.py}
setsid nohup /opt/conv/env/bin/python $W/job/drive.py $LABEL $W/job/$CONVF $W/job/$T --slots $S --threads $TH --vprocs $VP "$@" > $W/drive_$LABEL.log 2>&1 < /dev/null &
echo "launched $LABEL pid $!"
