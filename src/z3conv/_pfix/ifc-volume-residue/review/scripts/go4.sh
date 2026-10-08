#!/bin/bash
# reviewer job 4: strict-guard variant of patch 1 (bad1 == 0) on partial-repair + gain models
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-volume-residue-review
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-volume-residue-review
cd $W
PY=/opt/conv/env/bin/python
V6_VERIFY_PROCS=2 $PY pkg/batch3.py S_strict $W/pkg/conv_strict $W/pkg/kit2 pkg/models_S.json --jobs 2 > S_strict.log 2>&1; aws s3 cp --quiet S_strict.log $R/S_strict.log
