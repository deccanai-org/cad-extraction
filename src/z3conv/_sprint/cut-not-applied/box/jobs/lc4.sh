#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/len_check.py tools/
for id in e151a8faacbce446 575da79b6096c760; do echo "== $id"; PERPROF=1 KIT=$W/kitnp9 timeout 1500 /opt/conv/env/bin/python tools/len_check.py $id pipes5/kitn/$id pipes5/kitnp9/$id 2>&1 | grep -v "ALL PROF" | head -60 | sort -k2,2 -s | head -40; done
