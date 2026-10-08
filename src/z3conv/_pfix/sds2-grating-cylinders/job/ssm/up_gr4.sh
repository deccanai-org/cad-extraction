#!/bin/bash
WD=/work/agentwork/sds2-grating-cylinders; cd $WD
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-grating-cylinders
mkdir -p gr4p; cp gr4/*.json gr4p/ 2>/dev/null; aws s3 cp --recursive --quiet gr4p $OUT/gr4p/ && echo uploaded; ls gr4
ps -eo pid,etime,args | grep "gr4.py" | grep -v grep | grep -v timeout | awk '{print $1, $2, $NF}'
