#!/bin/bash
WD=/work/agentwork/sds2-grating-cylinders; cd $WD
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-grating-cylinders
aws s3 cp --recursive --quiet rod1 $OUT/rod1/ && echo uploaded
ps -eo pid,etime,args | grep rod1.py | grep -v grep | cut -c1-150
