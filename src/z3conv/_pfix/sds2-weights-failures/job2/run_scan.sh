#!/bin/bash
W=/work/agentwork/sds2-weights-failures; mkdir -p $W/j2; cd $W/j2
for f in s2scan.py s2_ids.txt ve_ids.txt; do aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/j2/$f .; done
timeout 300 /opt/conv/env/bin/python s2scan.py s2_ids.txt ve_ids.txt scan.json && aws s3 cp --only-show-errors scan.json s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-weights-failures/j2/scan.json && echo uploaded
