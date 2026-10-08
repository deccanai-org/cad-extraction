#!/bin/bash
W=/work/agentwork/sds2-weights-failures/j2; cd $W
for f in ntscan.py nt_ids.txt; do aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/j2/$f .; done
timeout 300 /opt/conv/env/bin/python ntscan.py nt_ids.txt nt.json && aws s3 cp --only-show-errors nt.json s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-weights-failures/j2/nt.json && echo uploaded
