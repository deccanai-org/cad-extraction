W=/work/agentwork/sds2-pieces-not-built; cd $W
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-pieces-not-built/probe_misc.py stage/probe_misc.py
P="$W/env/bin/python stage/probe_misc.py $W/base54/sds2-step-pipeline/decode"
timeout 100 $P cv $W/jobs/PSU_BNR_JOB_mallesh_4e9908 623,1806,1807 2>&1 | tail -8
timeout 100 $P fb $W/jobs/THERMOFISHER_JOB_bff8f8 73,80,104,106,107,132 2>&1 | tail -10
timeout 60 $P atr $W/jobs/SLC5_DATABANK_JOB_f0c2c8 3932 2>&1 | tail -10
