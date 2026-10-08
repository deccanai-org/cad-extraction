#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/bbox_truth.py tools/
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
timeout 1500 /opt/conv/env/bin/python tools/bbox_truth.py gsk pipes3/fit/truth_gsk > res/bbox_gsk.txt 2>&1; aws s3 cp --quiet res/bbox_gsk.txt $OUT/truth13/
until [ -f pipes3/fit/truth_iron/pipe.json ]; do sleep 20; done
timeout 2400 /opt/conv/env/bin/python tools/bbox_truth.py iron pipes3/fit/truth_iron 3000 > res/bbox_iron.txt 2>&1; aws s3 cp --quiet res/bbox_iron.txt $OUT/truth13/
