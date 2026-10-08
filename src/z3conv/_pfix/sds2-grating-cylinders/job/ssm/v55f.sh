#!/bin/bash
W=/work/agentwork/sds2-grating-cylinders; cd $W
rm -rf v55f; mkdir -p v55f
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-grating-cylinders/v55f.tgz .
tar xzf v55f.tgz -C v55f && grep -c "_cap_axis_cylinders" v55f/sds2-step-pipeline/decode/to_step2.py
for n in SHERIFFS_OFFICE_JOB_e730aa DSCC_JOB_ef345b; do setsid nohup bash conv.sh v55f $W/jobs/$n > /dev/null 2>&1 < /dev/null & done
echo launched
