#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/len_check.py tools/; ls reports | head -40 | tr '\n' ' '; echo
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
for id in 0762effe61de88c0 e151a8faacbce446 6304887153755ea3 575da79b6096c760; do
  [ -d reports/$id ] && [ ! -d reports/${id:0:4} ] && ln -s $W/reports/$id reports/${id:0:4}
  echo "== $id"; KIT=$W/kitnp9 timeout 1500 /opt/conv/env/bin/python tools/len_check.py $id pipes5/kitn/$id pipes5/kitnp9/$id 2>&1 | tail -3
done > res/netmatch_final.txt
aws s3 cp --quiet res/netmatch_final.txt $OUT/final/; cat res/netmatch_final.txt
