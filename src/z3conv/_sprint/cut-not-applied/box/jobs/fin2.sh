#!/bin/bash
# final evidence with the final kit kitnp7 (code n + P1-P14, refined line-cut side): (1) corpus convert-only vs deployed code n (kitn);
# (2) full worker pipelines kitn vs kitnp7; (3) truth pipelines (iron, gsk) kitnp7 vs code n
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/*.py stage/tools/*.sh tools/ 2>/dev/null
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
rm -rf kitnp7; cp -r kitn kitnp7; /opt/conv/env/bin/python stage/patch2/apply_cut_patch.py kitnp7 > res/patch_kitnp7.txt 2>&1 && touch kitnp7/.patched; tail -1 res/patch_kitnp7.txt
[ -f kitnp7/.patched ] || exit 1
md5sum kitnp7/db1old.py kitnp7/db1dec.py kitnp7/db1step.py kitnp7/fittings.py > res/kitnp7.md5; aws s3 cp --quiet res/kitnp7.md5 $OUT/final/
run() { k=$1; id=$2; O=$W/convall/$k/$id; [ -f $O/conv.json ] && return; bash $W/tools/conv_only.sh $W/$k $id $O; }
run_one() { v=$1; id=$2; O=$W/pipes5/$v/$id; [ -f $O/pipe.json ] && return; bash $W/tools/pipe.sh $W/$v $id $O; echo "done $v $id"; }
export -f run run_one; export W
( ( for id in $(cat res/convn.lst); do echo "kitnp7 $id"; done ) | xargs -P 8 -L 1 bash -c 'run $0 $1'
  /opt/conv/env/bin/python tools/cvsum2.py kitn kitnp7 > res/convn7_sum.txt 2>&1; aws s3 cp --quiet res/convn7_sum.txt $OUT/final/convn7_sum.txt; echo CORPUSDONE ) &
( for id in 0762effe61de88c0 truth_gsk e151a8faacbce446 6304887153755ea3 575da79b6096c760 6eabb07e71459be6 truth_iron 1d8972fb557e3371 4518a79a995bdee0 a94442572f225f50; do echo "kitn $id"; echo "kitnp7 $id"; done ) | xargs -P 3 -L 1 bash -c 'run_one $0 $1'
for n in iron gsk; do KIT=$W/kitnp7 /opt/conv/env/bin/python tools/truth_cmp2.py $n coden=pipes5/kitn/truth_$n final=pipes5/kitnp7/truth_$n > res/truth_final_$n.txt 2>&1; aws s3 cp --quiet res/truth_final_$n.txt $OUT/final/; done
wait
echo FIN2DONE
