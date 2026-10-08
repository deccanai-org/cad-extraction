#!/bin/bash
cd /data/s3d/src
cp /data/s3d/work/pcf_validation.json /data/s3d/work/pcf_validation_v2_before_conventions.json
$PY regen_pcf.py
$PY pcfval.py run --workers 8
echo REGEN_VAL_DONE
