#!/bin/bash
# conv_skip.sh VARIANT JOBDIR: run conv.sh unless that (variant, job) has already been started (its out dir exists)
W=/work/agentwork/sds2-approx-pieces-7x
V=$1; J=$2; N=$(basename "$J")
[ -d $W/out/$V/$N ] && exit 0
bash $W/conv.sh $V $J
