#!/bin/bash
# final evidence: (1) corpus convert-only with the final kit kitnp6 vs deployed code n (kitn); (2) full worker pipelines kitn vs kitnp6
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/*.py stage/tools/*.sh tools/ 2>/dev/null
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
until [ -f kitnp6/.patched ]; do sleep 10; done
run() { k=$1; id=$2; O=$W/convall/$k/$id; [ -f $O/conv.json ] && return; bash $W/tools/conv_only.sh $W/$k $id $O; }
run_one() { v=$1; id=$2; O=$W/pipes4/$v/$id; [ -f $O/pipe.json ] && return
  if [ "$v" = kitn ]; then bash $W/tools/pipe.sh $W/kitn $id $O; else bash $W/tools/pipe.sh $W/kitnp6 $id $O; fi; echo "done $v $id"; }
export -f run run_one; export W
( ( for id in $(cat res/convn.lst); do echo "kitnp6 $id"; done ) | xargs -P 8 -L 1 bash -c 'run $0 $1'
  /opt/conv/env/bin/python tools/cvsum2.py kitn kitnp6 > res/convn6_sum.txt 2>&1; aws s3 cp --quiet res/convn6_sum.txt $OUT/final/convn6_sum.txt; echo CORPUSDONE ) &
( for id in 0762effe61de88c0 e151a8faacbce446 6304887153755ea3 575da79b6096c760 6eabb07e71459be6 1d8972fb557e3371 4518a79a995bdee0; do echo "kitn $id"; echo "fit $id"; done; echo "kitn a94442572f225f50" ) | xargs -P 3 -L 1 bash -c 'run_one $0 $1'
wait
echo FINDONE
