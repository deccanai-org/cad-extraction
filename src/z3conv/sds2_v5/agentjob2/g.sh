#!/bin/bash
W=/work/agentwork/sds2v54
cd $W
export AWS_DEFAULT_REGION=ap-south-1
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2v54/v54g.tgz $W/v54g.tgz
mkdir -p $W/v54g && tar xzf $W/v54g.tgz -C $W/v54g
ls -d $W/jobs/GMS $W/jobs/METHODIST* $W/jobs/AGNEWS_HS_Bldg-T* $W/jobs/TYSONS* $W/jobs/160920_AGNEWS* > $W/g_dirs.txt
cat $W/g_dirs.txt | xargs -P 5 -I{} bash $W/conv.sh v54g {}
date -u +%FT%TZ > $W/G_DONE
aws s3 cp --quiet $W/G_DONE s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/G_DONE
