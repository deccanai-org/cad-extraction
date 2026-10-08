#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
aws s3 cp --quiet s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/conv/index.jsonl.gz data/index.jsonl.gz
/opt/conv/env/bin/python tools/survey_results.py > data/survey.txt 2>&1
aws s3 cp --quiet data/survey.txt $OUT/survey/survey.txt; aws s3 cp --quiet data/db1_all.json $OUT/survey/db1_all.json
cat data/survey.txt
