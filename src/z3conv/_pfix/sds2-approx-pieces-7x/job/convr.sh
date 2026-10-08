#!/bin/bash
# replaces the convb / convc queues: the remaining (job, variant) pairs of dirs_conv.txt, both variants of a job
# next to each other, 6 at a time; pairs already started keep running and are skipped here
W=/work/agentwork/sds2-approx-pieces-7x
exec > $W/convr.log 2>&1
cd $W
for p in $(ps -eo pid,args | grep -E "conv_all.sh dirs_conv.txt (base553|cand9)" | grep -v grep | awk '{print $1}'); do kill $p; done
for p in $(ps -eo pid,args | grep -E "xargs -P [34] -L 1 bash -c bash $W/conv.sh" | grep -v grep | awk '{print $1}'); do kill $p; done
sleep 2
for J in $(cat $W/dirs_conv.txt); do echo "cand9 $J"; echo "base553 $J"; done | xargs -P ${NP:-6} -L 1 bash -c 'bash '$W'/conv_skip.sh $0 $1'
date -u +%FT%TZ > $W/convr_DONE; aws s3 cp --quiet $W/convr_DONE s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-approx-pieces-7x/convr_DONE
