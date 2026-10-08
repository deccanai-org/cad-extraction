#!/bin/bash
W=/work/agentwork/sds2-recall-nc1
cd $W && aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-recall-nc1/explain.py .
for j in 723d542e 0c105e89 643a5f2c 7d979650; do timeout 30 /opt/conv/env/bin/python explain.py $j; done
