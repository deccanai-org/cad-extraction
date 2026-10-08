W=/work/agentwork/sds2-pieces-not-built; cd $W
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-pieces-not-built/probe_ds.py stage/probe_ds.py
P="$W/env/bin/python stage/probe_ds.py $W/base54/sds2-step-pipeline/decode"
timeout 100 $P out/cls/0ec369310a9c109281e12fe4.json $W/jobs/hjj_0ec369 2>&1 | head -20
timeout 100 $P out/cls/1d160f*.json $W/jobs/hjjj_1d160f closed+degenerate 2>&1 | head -20
