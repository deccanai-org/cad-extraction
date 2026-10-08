#!/bin/bash
# base553 + cand9 conversions of the two 7.708 models whose only class-1 blocker is approximate curved HSS
W=/work/agentwork/sds2-approx-pieces-7x
exec > $W/convd.log 2>&1
cd $W
bash $W/conv_all.sh dirs_conv2.txt "base553 cand9" 2 convd
