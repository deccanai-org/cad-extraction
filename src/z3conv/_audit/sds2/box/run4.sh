#!/bin/bash
cd /work/agentwork/audit-sds2-pipeline
aws s3 cp s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/audit-sds2-pipeline/guidcheck.py . --quiet --region ap-south-1
timeout 900 /opt/conv/env/bin/python guidcheck.py df70ab5000794e4a5bab3a0a bbc38a2b78fed0fddbebdf45 41a7e3efb613e7b9aa194575 2>&1 | tee guidcheck.out | tail -120
aws s3 cp guidcheck.out s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/audit-sds2-pipeline/diag/guidcheck.out --quiet --region ap-south-1
