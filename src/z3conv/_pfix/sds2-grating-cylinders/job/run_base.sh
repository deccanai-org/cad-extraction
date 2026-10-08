#!/bin/bash
W=/work/agentwork/sds2-grating-cylinders; cd $W
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-grating-cylinders/jobs_ba.txt .
cat jobs_ba.txt | xargs -P 6 -I{} bash $W/conv.sh base54 {}
date -u +%FT%TZ > BASE_DONE; aws s3 cp --quiet BASE_DONE s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-grating-cylinders/BASE_DONE
