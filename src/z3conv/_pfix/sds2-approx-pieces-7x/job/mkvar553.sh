#!/bin/bash
# mkvar553.sh NAME FILE:DEST [FILE:DEST ...] -> $W/NAME = v5.5.3 + replaced decode files
W=/work/agentwork/sds2-approx-pieces-7x
N=$1; shift
rm -rf $W/$N; mkdir -p $W/$N; cp -r $W/b553/sds2-step-pipeline $W/$N/
for fd in "$@"; do f=${fd%%:*}; d=${fd##*:}; cp $W/$f $W/$N/sds2-step-pipeline/decode/$d; done
find $W/$N -name __pycache__ -prune -exec rm -rf {} \;
echo made $N
