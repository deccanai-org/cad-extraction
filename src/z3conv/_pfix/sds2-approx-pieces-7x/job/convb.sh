#!/bin/bash
# base553 conversions (stage 2 --verify) on dirs_conv.txt, 4 at a time (baseline for the before/after table)
W=/work/agentwork/sds2-approx-pieces-7x
exec > $W/convb.log 2>&1
cd $W
while [ ! -d $W/base553/sds2-step-pipeline ]; do sleep 10; done
bash $W/conv_all.sh dirs_conv.txt "base553" ${NP:-4} convb
