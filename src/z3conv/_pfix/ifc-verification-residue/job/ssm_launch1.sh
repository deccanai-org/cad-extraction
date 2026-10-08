#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue
bash $W/job/launch.sh mnc_dev3 targets_mnc.json 2 2 2
bash $W/job/launch.sh ppv_dev3 targets_ppv1.json 2 4 4
sleep 20
ps -eo pid,pcpu,rss,etimes,args | grep -E "ifc-verification-residue" | grep -v grep | cut -c1-200
tail -5 $W/drive_mnc_dev3.log $W/drive_ppv_dev3.log
