#!/bin/bash
# run7.sh (1 proc): close-up renders of bolted connections from deployed STEP (.i) for render spot-checks
cd /work/agentwork/audit-db1-codes; mkdir -p report/renders
P=/opt/conv/env/bin/python
r() { id=$(ls src | grep "^$1" | head -1); id=${id%.db1}; [ -f out/$id$2.stp ] || return
  timeout 900 $P render_closeup.py out/$id$2.stp det/$id$2.step_parts.jsonl.gz report/renders/${1}$2_p$3.png --pick $3 --margin ${4:-150} --title "$1$2 pick $3" >> logs/render.log 2>&1; }
r 0632e878d57c .i 5; r 0632e878d57c .i 60; r 0632e878d57c .i 120
r 12cbdcaaec9e .i 10; r 12cbdcaaec9e .i 200
r 575da79b6096 .i 30
r 0dd3da934923 .i 50 300
aws s3 cp report/renders/ s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/audit-db1-codes/report/renders/ --recursive --only-show-errors
echo done >> logs/render.log
