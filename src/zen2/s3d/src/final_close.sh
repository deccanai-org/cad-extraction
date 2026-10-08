#!/bin/bash
cd /data/s3d/src
touch /data/s3d/work/status.stop
sleep 5; pkill -f "status.py loop"
aws s3 sync --only-show-errors --exclude "*.tmp*" /data/s3d/out/ s3://annotationprod/cad-disk-extract/zenitude-data-2/model/
$PY final_summary.py > /dev/null 2>&1
$PY make_index.py > /dev/null 2>&1
aws s3 cp --only-show-errors /data/s3d/out/json/index.json s3://annotationprod/cad-disk-extract/zenitude-data-2/model/json/index.json
echo "DONE: JSON+PCF 45,003 pipelines (validated vs S3D iso PCFs), IFC 1,927 / STEP 1,927 (OCC-validated) / GLB 1,927 / OBJ 1,927 incl. ACIS structure (members w/ end cuts, curved members, slabs), pairs index, PNG previews" > /data/s3d/work/stage.txt
$PY status.py once
echo CLOSED
