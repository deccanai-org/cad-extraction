W=/work/agentwork/sds2-pieces-not-built; cd $W
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-pieces-not-built/probe_caseb2.py stage/probe_caseb2.py
timeout 100 $W/env/bin/python stage/probe_caseb2.py $W/base54/sds2-step-pipeline/decode $W/jobs/jfkf_23c107 74501 74488 74521 2>&1 | head -60
