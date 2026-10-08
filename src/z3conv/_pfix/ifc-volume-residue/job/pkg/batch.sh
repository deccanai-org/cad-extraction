#!/bin/bash
# batch.sh LABEL CONVERTER [extra batch.py args] - runs on BOX-A as root under /work/agentwork/ifc-volume-residue
LABEL=$1; CONV=$2; shift 2
W=/work/agentwork/ifc-volume-residue
export AWS_DEFAULT_REGION=ap-south-1 KIT=$W/pkg/kit COORD=$W/pkg/coord CONV_HOME=/opt/conv INDEX_WORK=$W/index V6_VERIFY_PROCS=${V6_VERIFY_PROCS:-2}
mkdir -p $W/w $W/in $W/index
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-volume-residue
/opt/conv/env/bin/python $W/pkg/batch.py $LABEL $CONV --models $W/pkg/models.json --out $W/w --indir $W/in --s3 $R "$@" > $W/batch_$LABEL.log 2>&1
aws s3 cp --quiet $W/batch_$LABEL.log $R/$LABEL/batch.log
