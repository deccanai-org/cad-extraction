#!/bin/bash
W=/work/agentwork/sds2-weights-failures-review; mkdir -p $W/grading; cd $W
for f in gradechk.py build_index.cur.py build_index.new.py worker.cur.py worker.new.py grade_join.py rules.json sds2_versions.py; do aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures-review/$f $W/grading/; done
cp $W/grading/gradechk.py $W/
timeout 900 $W/env/bin/python $W/gradechk.py $W/grade.json b553:$W/trees/b553/sds2-step-pipeline w553:$W/trees/w553/sds2-step-pipeline:new b555:$W/trees/b555/sds2-step-pipeline b54:$W/trees/b54/sds2-step-pipeline w54:$W/trees/w54/sds2-step-pipeline:new w553nx:$W/trees/w553/sds2-step-pipeline:new 2>&1 | tail -5
aws s3 cp --only-show-errors $W/grade.json s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-weights-failures-review/grade.json && echo uploaded
