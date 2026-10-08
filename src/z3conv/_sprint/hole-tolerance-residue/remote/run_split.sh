#!/bin/bash
cd /work/agentwork/hole-tolerance-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/hole-tolerance-residue/splitcmp.py .
ls full/kit_jg/291547d3c10f/ full/kit_jp/291547d3c10f/
timeout 100 conv/env/bin/python splitcmp.py 291547d3c10f
