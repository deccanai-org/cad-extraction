#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/bbox_pair.py tools/
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
KIT=$W/kitnp9 timeout 3600 /opt/conv/env/bin/python tools/bbox_pair.py gambro ifconly/kitn/truth_gambro ifconly/kitnp8/truth_gambro > res/bboxpair_gambro.txt 2>&1
aws s3 cp --quiet res/bboxpair_gambro.txt $OUT/final/; cat res/bboxpair_gambro.txt | cut -c1-400
