W=/work/agentwork/sds2-pieces-not-built; cd $W
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-pieces-not-built/probe_slot.py $W/stage/probe_slot.py
timeout 300 nice $W/env/bin/python $W/stage/probe_slot.py $W/trees/v553/decode 2>&1 | tail -20
