#!/bin/bash
# Mac: copy the small evidence files (JSON / txt) from the box results in S3 into the Mac dir (no STEP, no parts files)
S3=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/step-verify-big
D=/Users/dhiren/Downloads/Deccan/z3conv/_fast/step-verify-big
mkdir -p $D/equiv/box $D/final/results $D/runs/box
for f in equiv_p1.json equiv_p1.txt equiv_p1_early.json equiv_p2.json equiv_p2.txt; do AWS_PROFILE=bim aws s3 cp --only-show-errors $S3/out/$f $D/equiv/box/$f 2>/dev/null; done
for f in models.json runs.json predict.json predict.txt post.txt; do AWS_PROFILE=bim aws s3 cp --only-show-errors $S3/final/$f $D/final/$f 2>/dev/null; done
AWS_PROFILE=bim aws s3 cp --only-show-errors --recursive $S3/final/results/ $D/final/results/ 2>/dev/null
AWS_PROFILE=bim aws s3 cp --only-show-errors $S3/status_main.json $D/runs/box/status_main.json 2>/dev/null
AWS_PROFILE=bim aws s3 cp --only-show-errors --recursive $S3/out/ $D/runs/box/out/ --exclude "*" --include "*.json" --exclude "*/final_readback_*" 2>/dev/null
ls -la $D/equiv/box $D/final | head -30
