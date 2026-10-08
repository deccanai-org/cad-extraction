#!/bin/bash
# Binney v5.4 early run (separate output v54b): download, extract with 7zz, convert without read-back preview
W=/work/agentwork/sds2v54
mkdir -p $W/jobs/b2
cd $W/jobs/b2
export AWS_DEFAULT_REGION=ap-south-1
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2v54/v54.tgz $W/v54b.tgz
mkdir -p $W/v54b && tar xzf $W/v54b.tgz -C $W/v54b
aws s3 cp --only-show-errors "s3://bim-proprietary-data/Disk-2/Completed_Jobs_Data/SDS_Jobs_7.243/CIVES NEW ENGLAND/50_Binney_Job.7z" binney.7z
/usr/local/bin/7zz x -y -obinney binney.7z > /dev/null
bash $W/conv.sh v54b $W/jobs/b2/binney/50_Binney_Job noverify
