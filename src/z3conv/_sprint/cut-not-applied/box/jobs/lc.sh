#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/len_check.py tools/
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
timeout 1200 /opt/conv/env/bin/python tools/len_check.py 0762effe61de88c0 pipes5/kitn/0762effe61de88c0 pipes5/kitnp7/0762effe61de88c0 '[200*90*8*13.5' 'L150*90*10' 'L65*65*6' 'L50*50*6' 'L100*75*10' > res/lencheck_0762.txt 2>&1
aws s3 cp --quiet res/lencheck_0762.txt $OUT/final/; cat res/lencheck_0762.txt
