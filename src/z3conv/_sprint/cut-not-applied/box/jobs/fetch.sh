#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
/opt/conv/env/bin/python tools/survey_keys2.py 2>&1 | tail -30
aws s3 cp --quiet data/db1_all.json $OUT/survey/db1_all.json
/opt/conv/env/bin/python tools/fetch_all.py src 200 2>&1 | tail -30
du -sh src; ls src | wc -l
