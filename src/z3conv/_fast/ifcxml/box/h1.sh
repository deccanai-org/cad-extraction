#!/bin/bash
mkdir -p /work/agentwork/ifcxml/h1 && cd /work/agentwork/ifcxml/h1
aws s3 cp s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifcxml/find_inputs.py . --only-show-errors
FIND_WORK=find FIND_THREADS=32 timeout 900 /opt/conv/env/bin/python find_inputs.py ifcheads 2>&1 | tail -5
