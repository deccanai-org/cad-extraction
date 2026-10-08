#!/bin/bash
# v5.4 final code check (v54f) on jobs already fetched: Greenwood + 5 data-4 jobs, 4 at a time, + NC1 on Greenwood
W=/work/agentwork/sds2v54
cd $W
export AWS_DEFAULT_REGION=ap-south-1
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2v54/v54f.tgz $W/v54f.tgz
mkdir -p $W/v54f && tar xzf $W/v54f.tgz -C $W/v54f
ls -d $W/jobs/GMS $W/jobs/160920_AGNEWS* $W/jobs/TYSONS* $W/jobs/METHODIST* $W/jobs/AGNEWS_HS_Bldg-T* $W/jobs/defaultAdapt* > $W/final_dirs.txt
cat $W/final_dirs.txt | xargs -P 4 -I{} bash $W/conv.sh v54f {}
$W/env/bin/python $W/v54f/sds2-step-pipeline/qa/nc1_holes.py $W/jobs/GMS $W/gms_gt --pieces-csv $W/out/v54f/GMS/GMS_stage2_pieces.csv --manifest $W/out/v54f/GMS/GMS_stage2_manifest.json -o $W/out/v54f/GMS/nc1_holes_final.json > $W/out/v54f/GMS/nc1_final.log 2>&1
aws s3 cp --quiet $W/out/v54f/GMS/nc1_holes_final.json s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/v54f/GMS/nc1_holes_final.json
date -u +%FT%TZ > $W/FINAL_DONE
aws s3 cp --quiet $W/FINAL_DONE s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/FINAL_DONE
