#!/bin/bash
cd /work/agentwork/audit-sds2-pipeline
aws s3 cp s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/audit-sds2-pipeline/d7_incomplete.py . --quiet --region ap-south-1
timeout 600 /opt/conv/env/bin/python d7_incomplete.py 2>&1 | tail -30
