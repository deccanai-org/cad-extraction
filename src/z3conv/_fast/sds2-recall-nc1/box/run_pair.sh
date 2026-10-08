#!/bin/bash
W=/work/agentwork/sds2-recall-nc1
cd $W && aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-recall-nc1/pair_jobs.py .
timeout 110 /opt/conv/env/bin/python pair_jobs.py 2>&1 | tail -5
