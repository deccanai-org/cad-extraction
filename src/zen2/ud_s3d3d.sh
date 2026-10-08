#!/bin/bash
# Zenitude-data-2 3D conversion worker (IFC -> STEP / GLB / OBJ), builder's kit from S3.
exec > /var/log/s3d3d-boot.log 2>&1
set -x
export AWS_DEFAULT_REGION=ap-south-1
mkdir -p /opt/s3d3d
aws s3 cp --region ap-south-1 s3://annotationprod/cad-disk-extract/zenitude-data-2/_control/s3d3d/run.sh /tmp/run.sh && WORKDIR=/opt/s3d3d/work bash /tmp/run.sh
echo "$(date -u +%FT%TZ) $(hostname) boot done" | aws s3 cp --region ap-south-1 - s3://annotationprod/cad-disk-extract/zenitude-data-2/_state/s3d3d/boot/$(hostname).txt
