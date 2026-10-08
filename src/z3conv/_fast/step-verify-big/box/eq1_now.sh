#!/bin/bash
cd /work/agentwork/step-verify-big
/opt/conv/env/bin/python pkg/equiv_summary.py pkg/spec_p1.json out/equiv_p1_early.json > out/equiv_p1_early.txt 2>&1
aws s3 cp --only-show-errors out/equiv_p1_early.json s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/step-verify-big/out/equiv_p1_early.json
cat out/equiv_p1_early.txt
