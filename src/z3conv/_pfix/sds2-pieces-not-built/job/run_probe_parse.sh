W=/work/agentwork/sds2-pieces-not-built; cd $W
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-pieces-not-built/probe_parse.py stage/probe_parse.py
timeout 250 $W/env/bin/python stage/probe_parse.py $W/base54/sds2-step-pipeline/decode $W/jobs/hjj_0ec369 2>&1 | tail -12
