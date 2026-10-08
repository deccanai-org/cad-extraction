#!/bin/bash
# optional PNG pass, then final summaries/index/status; stops the status loop at the end
cd /data/s3d/src
echo "4 done: STEP (OCC-validated), GLB, OBJ for all 1,927 IFC files; 5: optional PNG previews rendering" > /data/s3d/work/stage.txt
$PY png_chunks.py --procs 6 > /data/s3d/logs/png_chunks.log 2>&1
# wait for the area composite worker
for i in $(seq 1 240); do pgrep -f "worker.py --png" > /dev/null || break; sleep 30; done
$PY final_summary.py > /data/s3d/logs/final_summary.log 2>&1
$PY make_index.py >> /data/s3d/logs/final_summary.log 2>&1
aws s3 cp --only-show-errors /data/s3d/out/json/index.json s3://annotationprod/cad-disk-extract/zenitude-data-2/model/json/index.json
echo "DONE: JSON+PCF (45,003 pipelines), IFC4 1,927 files, STEP 1,927 (OCC read-back ok), GLB 1,927, OBJ 1,927, PNG previews" > /data/s3d/work/stage.txt
$PY status.py once
touch /data/s3d/work/status.stop
echo FINALIZED
