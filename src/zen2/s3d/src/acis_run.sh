#!/bin/bash
cd /data/s3d/src
echo "7: ACIS SAB decode of member/slab solids running (JSON/PCF/IFC/STEP/GLB/OBJ done; pairs + pcf_validation done)" > /data/s3d/work/stage.txt
$PY acis_extract.py plan
$PY acis_extract.py run --workers 8
echo ACIS_DONE
