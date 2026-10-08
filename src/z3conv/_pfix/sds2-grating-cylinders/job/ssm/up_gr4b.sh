#!/bin/bash
WD=/work/agentwork/sds2-grating-cylinders; cd $WD
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-grating-cylinders
aws s3 cp --recursive --quiet gr4b $OUT/gr4b/ && echo uploaded; ls gr4b
grep -v LD_PRELOAD logs/gr4b.log | grep Trace -A5 | head -20
ps -eo pid,etime,args | grep "gr4.py" | grep -v grep | grep -v timeout | awk '{print $1, $2, $NF}'
