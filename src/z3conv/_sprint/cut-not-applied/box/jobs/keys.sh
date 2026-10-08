#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
/opt/conv/env/bin/python tools/survey_keys.py 2>&1 | tee data/keys.txt
aws s3 cp --quiet data/db1_all.json $OUT/survey/db1_all.json
