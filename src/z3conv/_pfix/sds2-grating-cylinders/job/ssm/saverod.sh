#!/bin/bash
W=/work/agentwork/sds2-grating-cylinders; cd $W
ls rod2/v55 | wc -l
aws s3 cp --recursive --quiet rod2 s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-grating-cylinders/rod2/ && echo saved
