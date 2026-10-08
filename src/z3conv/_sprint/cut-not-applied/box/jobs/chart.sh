#!/bin/bash
cd /work/agentwork/cut-not-applied; cp stage/tools/chart_report.py tools/
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
/opt/conv/env/bin/python tools/chart_report.py res/report_cmp_dec.txt renders/report_count_error.png && aws s3 cp --quiet renders/report_count_error.png $OUT/renders/
export PIPE_A=pipes2/kit2 PIPE_B=pipes2/kitp3
/opt/conv/env/bin/python tools/hot_cmp.py e151a8faacbce446 575da79b6096c760 > res/hot_cmp3.txt 2>&1; aws s3 cp --quiet res/hot_cmp3.txt $OUT/pipes2/hot_cmp3.txt; cat res/hot_cmp3.txt | cut -c1-250
