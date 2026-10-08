#!/bin/bash
# FINAL evidence with the final kit kitnp9 (code n + P1-P15): corpus convert-only + full pipelines vs deployed code n (kitn) + truth
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/*.py stage/tools/*.sh tools/ 2>/dev/null
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
rm -rf kitnp9; cp -r kitn kitnp9; /opt/conv/env/bin/python stage/patch2/apply_cut_patch.py kitnp9 > res/patch_kitnp9.txt 2>&1 && touch kitnp9/.patched; tail -1 res/patch_kitnp9.txt
[ -f kitnp9/.patched ] || exit 1
md5sum kitnp9/db1old.py kitnp9/db1dec.py kitnp9/db1step.py kitnp9/fittings.py > res/kitnp9.md5; aws s3 cp --quiet res/kitnp9.md5 $OUT/final/; aws s3 cp --quiet res/patch_kitnp9.txt $OUT/final/
run() { k=$1; id=$2; O=$W/convall/$k/$id; [ -f $O/conv.json ] && return; bash $W/tools/conv_only.sh $W/$k $id $O; }
run_one() { v=$1; id=$2; O=$W/pipes5/$v/$id; [ -f $O/pipe.json ] && return; rm -rf $O; bash $W/tools/pipe.sh $W/$v $id $O; echo "done $v $id"; }
export -f run run_one; export W
( ( for id in $(cat res/convn.lst); do echo "kitnp9 $id"; done ) | xargs -P 8 -L 1 bash -c 'run $0 $1'
  /opt/conv/env/bin/python tools/cvsum2.py kitn kitnp9 > res/convn9_sum.txt 2>&1; aws s3 cp --quiet res/convn9_sum.txt $OUT/final/convn9_sum.txt; echo CORPUSDONE ) &
( for id in 0762effe61de88c0 truth_iron truth_gsk e151a8faacbce446 6304887153755ea3 575da79b6096c760 6eabb07e71459be6 1d8972fb557e3371 a94442572f225f50 4518a79a995bdee0; do echo "kitn $id"; echo "kitnp9 $id"; done ) | xargs -P 3 -L 1 bash -c 'run_one $0 $1'
for n in iron gsk; do KIT=$W/kitnp9 /opt/conv/env/bin/python tools/truth_cmp2.py $n coden=pipes5/kitn/truth_$n final=pipes5/kitnp9/truth_$n > res/truth_final_$n.txt 2>&1; aws s3 cp --quiet res/truth_final_$n.txt $OUT/final/; done
KIT=$W/kitnp9 timeout 2400 /opt/conv/env/bin/python tools/bbox_truth.py iron pipes5/kitnp9/truth_iron 3000 > res/bbox_final_iron.txt 2>&1; aws s3 cp --quiet res/bbox_final_iron.txt $OUT/final/
KIT=$W/kitnp9 timeout 2400 /opt/conv/env/bin/python tools/bbox_truth.py iron pipes5/kitn/truth_iron 3000 > res/bbox_coden_iron.txt 2>&1; aws s3 cp --quiet res/bbox_coden_iron.txt $OUT/final/
KIT=$W/kitnp9 timeout 1200 /opt/conv/env/bin/python tools/len_check.py 0762effe61de88c0 pipes5/kitn/0762effe61de88c0 pipes5/kitnp9/0762effe61de88c0 '[200*90*8*13.5' 'L150*90*10' 'L65*65*6' 'L50*50*6' 'L100*75*10' > res/lencheck_final_0762.txt 2>&1; aws s3 cp --quiet res/lencheck_final_0762.txt $OUT/final/
for id in 0762effe61de88c0 e151a8faacbce446 6304887153755ea3 575da79b6096c760 6eabb07e71459be6 1d8972fb557e3371 a94442572f225f50 4518a79a995bdee0 truth_iron truth_gsk; do
  PIPE_A=pipes5/kitn PIPE_B=pipes5/kitnp9 /opt/conv/env/bin/python tools/pipe_cmp.py $id 2>&1 | grep "^{" ; done > res/pipecmp_final.jsonl
aws s3 cp --quiet res/pipecmp_final.jsonl $OUT/final/
wait
echo FIN3DONE
