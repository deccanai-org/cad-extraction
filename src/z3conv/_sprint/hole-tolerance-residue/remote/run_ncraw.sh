#!/bin/bash
cd /work/agentwork/hole-tolerance-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/hole-tolerance-residue/nc_raw.py .
timeout 100 /opt/conv/env/bin/python nc_raw.py a7f94f2edc0f 2>&1 | tail -40
