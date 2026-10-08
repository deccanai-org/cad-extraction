#!/bin/bash
cd /work/agentwork/sds2-recall-nc1 && aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-recall-nc1/skipscan.py .
timeout 110 /opt/conv/env/bin/python skipscan.py
