#!/bin/bash
cd /data/s3d/src
$PY replan.py plan
$PY ifcjobs.py run --workers 6
$PY publish_fanout.py --final
$PY replan.py clean
$PY make_index.py
echo REPLAN_DONE
