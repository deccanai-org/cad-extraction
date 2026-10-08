#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/bbox_pair.py stage/tools/bbox_pair_drive.py tools/
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
export KIT=$W/kitnp9
timeout 7200 /opt/conv/env/bin/python tools/bbox_pair_drive.py gambro ifconly/kitn/truth_gambro ifconly/kitnp8/truth_gambro > res/bboxpair_gambro.txt 2>&1
aws s3 cp --quiet res/bboxpair_gambro.txt $OUT/final/
