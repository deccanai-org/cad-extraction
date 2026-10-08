#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
/opt/conv/env/bin/python tools/report_cmp_dec.py > res/report_cmp_dec.txt 2>&1
aws s3 cp --quiet res/report_cmp_dec.txt $OUT/report/report_cmp_dec.txt
tail -c 18000 res/report_cmp_dec.txt
