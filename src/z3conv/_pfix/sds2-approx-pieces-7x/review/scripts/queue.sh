#!/bin/bash
W=/work/agentwork/sds2-approx-pieces-7x-review
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-approx-pieces-7x-review
cd $W; exec > $W/queue.log 2>&1
{
 awk '$1=="claim"{print "conv base553 "$3; print "conv cand "$3}' dirs_all.txt
 awk '$1=="ctl"{print "conv base553 "$3; print "conv cand "$3}' dirs_all.txt
 awk '{print "audit x "$3}' dirs_all.txt
 awk '$1=="new"{print "conv base553 "$3; print "conv cand "$3}' dirs_all.txt
 awk '$1=="claim" && $2!="15bf82"{print "conv v556 "$3}' dirs_all.txt
} > tasks.txt
cat tasks.txt
cat tasks.txt | xargs -P ${NP:-14} -L 1 bash -c 'if [ "$0" = conv ]; then bash '$W'/conv.sh $1 $2; else bash '$W'/audit.sh $2; fi; echo "$(date -u +%T) done $0 $1 $2" >> '$W'/progress.txt; aws s3 cp --quiet '$W'/progress.txt '$R'/progress.txt'
date -u +%FT%TZ > QUEUE_DONE; aws s3 cp --quiet QUEUE_DONE $R/QUEUE_DONE
