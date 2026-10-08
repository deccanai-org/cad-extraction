#!/bin/bash
W=/work/agentwork/sds2-recall-nc1
cd $W && aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-recall-nc1/aggregate.py aggregate.py
timeout 100 /opt/conv/env/bin/python aggregate.py 2>&1 | head -200
