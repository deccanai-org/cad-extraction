#!/bin/bash
# copy report outputs from the box to bim cad-disk-extract/_state/report/ (our own report prefix) so the Mac can read them
export AWS_DEFAULT_REGION=ap-south-1
aws s3 sync --only-show-errors /opt/report/out/ s3://bim-proprietary-data/cad-disk-extract/_state/report/out/ --exclude "*.log" --exclude "*.started"
aws s3 sync --only-show-errors /opt/report/assets/ s3://bim-proprietary-data/cad-disk-extract/_state/report/assets/ --exclude "*.npy" --exclude "*.log" 2>/dev/null
echo pushed; ls -la /opt/report/out | tail -5
