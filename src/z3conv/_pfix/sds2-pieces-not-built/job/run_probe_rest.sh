W=/work/agentwork/sds2-pieces-not-built; cd $W
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-pieces-not-built/probe_rest.py stage/probe_rest.py
timeout 280 $W/env/bin/python stage/probe_rest.py 2>&1 | tail -12
