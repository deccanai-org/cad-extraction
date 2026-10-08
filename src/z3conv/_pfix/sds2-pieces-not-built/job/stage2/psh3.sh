W=/work/agentwork/sds2-pieces-not-built; cd $W
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-pieces-not-built/probe_sh3.py $W/stage/probe_sh3.py
timeout 300 $W/env/bin/python $W/stage/probe_sh3.py $W/trees/v553r/decode 19156_610_WALNUT_JOB_09152020_7773ea:2923,2807,537 2>&1 | tail -40
