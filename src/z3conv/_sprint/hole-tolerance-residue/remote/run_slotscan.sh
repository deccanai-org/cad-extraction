#!/bin/bash
S=hole-tolerance-residue; cd /work/agentwork/$S; export AWS_DEFAULT_REGION=ap-south-1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/$S/slotscan.py .
F=""; for p in 5a2284473e4e 6eabb07e7145 172ffb7a9ab8 863be0aa5b95 0632e878d57c 3355ebac77ad; do F="$F $(ls db1/$p*.db1)"; done
timeout 100 /opt/conv/env/bin/python slotscan.py $F 2>&1 | tail -40
