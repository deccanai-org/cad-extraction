#!/bin/bash
W=/work/agentwork/sds2-weights-failures; J=$W/j2; mkdir -p $J/grading $J/tmp; cd $J
C=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/j2
for f in gradecheck2.py promote_check.py inv39_ids.json; do aws s3 cp --only-show-errors $C/$f $J/$f; done
for f in build_index.cur.py build_index.new.py worker.cur.py worker.new.py grade_join.py; do aws s3 cp --only-show-errors $C/grading/$f $J/grading/$f; done
timeout 900 /opt/conv/env/bin/python promote_check.py inv39_ids.json pc39.json 2>&1 | tail -5
aws s3 cp --only-show-errors pc39.json s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-weights-failures/j2/pc39.json && echo up
