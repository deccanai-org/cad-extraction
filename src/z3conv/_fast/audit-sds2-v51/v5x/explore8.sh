#!/bin/bash
cd /work/agentwork/audit-sds2-v5x
export AWS_DEFAULT_REGION=ap-south-1
grep -E "2263534c2ceb0b6e28191b95|693974d8d7f81a01933b1d44" s3/out_listing.txt | grep '\.step$'
mkdir -p steps && cd steps
B=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/conversions/sds2-step
aws s3 cp --quiet $B/2263534c2ceb0b6e28191b95/VOID_226353_stage2.step VOID_v4.step
aws s3 cp --quiet $B/2263534c2ceb0b6e28191b95/v5.1/VOID_226353_stage2.step VOID_v51.step
for f in VOID_v4.step VOID_v51.step; do echo "$f bytes=$(stat -c%s $f) PRODUCT=$(grep -c "PRODUCT('" $f) approx_tagged=$(grep -c '\[approx' $f)"; grep -o "PRODUCT('[^']*\[approx[^']*'" $f | head -2; done
grep -o "PRODUCT('[^']*BOLT[^']*'" VOID_v4.step | head -2
