#!/bin/bash
# re-publish jobs.json every 3 min while IFC generation runs; final publish when it ends
cd /data/s3d/src
while pgrep -f "ifcjobs.py run" > /dev/null; do
  $PY publish_fanout.py > /data/s3d/logs/publish.log 2>&1
  sleep 180
done
$PY publish_fanout.py --final > /data/s3d/logs/publish.log 2>&1
$PY ifcjobs.py summary > /dev/null 2>&1
$PY make_index.py >> /data/s3d/logs/publish.log 2>&1
echo "3 done: IFC generated for all areas; 4: STEP/GLB/OBJ fan-out conversion running (job list final)" > /data/s3d/work/stage.txt
