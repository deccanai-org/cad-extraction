#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/*.py tools/
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
until [ -f kitn/worker.py ]; do sleep 5; done
rm -rf kitnp3; cp -r kitn kitnp3; /opt/conv/env/bin/python stage/patch2/apply_cut_patch.py kitnp3 > res/patch_kitnp3.txt 2>&1 && touch kitnp3/.patched; tail -1 res/patch_kitnp3.txt
for id in a95d70a8981d7cf7 a94442572f225f50 4fa8f263f754f862; do ( timeout 2400 /opt/conv/ifc84/bin/python tools/trace_unbuilt2.py kitnp3 src/$id.db1 > res/trace4_$id.txt 2>&1; aws s3 cp --quiet res/trace4_$id.txt $OUT/trace/ ) & done; wait
