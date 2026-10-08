#!/bin/bash
W=/work/agentwork/sds2-recall-nc1
cd $W && aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-recall-nc1/explain.py explain.py
for j in 2d75177c 42acb02c 700ec3ff 4d7a8a6f 723d542e; do timeout 40 /opt/conv/env/bin/python explain.py $j 2>&1 | grep -E "^[A-Z0-9].* (v4c|v5)|strict_zero|    SZ" | head -24; done
