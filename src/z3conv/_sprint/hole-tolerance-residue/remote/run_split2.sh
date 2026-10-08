#!/bin/bash
cd /work/agentwork/hole-tolerance-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/hole-tolerance-residue/splitcmp2.py .
timeout 100 conv/env/bin/python splitcmp2.py 291547d3c10f kit_jg kit_jp3
