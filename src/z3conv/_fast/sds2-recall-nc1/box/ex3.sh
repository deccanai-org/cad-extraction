#!/bin/bash
W=/work/agentwork/sds2-recall-nc1
cd $W
for j in 3db35c3d ba811fa9 cd34ed67; do timeout 40 /opt/conv/env/bin/python explain.py $j 2>&1 | grep -vE "^  (nc1_parts|nc1_marks|nc1_holes|step_unique|step_round|step_slots|manifest_counts|manifest_holes_not|manifest_class|approx)" | head -30; done
