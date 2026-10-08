W=/work/agentwork/sds2-pieces-not-built; cd $W
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-pieces-not-built/probe_sh.py $W/stage/probe_sh.py
timeout 100 $W/env/bin/python $W/stage/probe_sh.py $W/trees/v553/decode A-Practice_Job_1cd870:615 2>&1 | tail -5
