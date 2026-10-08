#!/bin/bash
W=/work/agentwork/sds2-grating-cylinders; cd $W
grep -v "One_Light_Tower\|SHERIFFS" jobs_ba.txt > jobs_v55.txt
cat jobs_v55.txt | xargs -P 6 -I{} bash $W/conv.sh v55 {}
date -u +%FT%TZ > V55_DONE; aws s3 cp --quiet V55_DONE s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-grating-cylinders/V55_DONE
