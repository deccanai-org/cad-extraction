#!/bin/bash
# corpus convert-only with the final kit kitnp8 (code n + P1-P15) vs deployed code n (kitn)
W=/work/agentwork/cut-not-applied; cd $W
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
until [ -f kitnp8/.patched ]; do sleep 10; done
run() { k=$1; id=$2; O=$W/convall/$k/$id; [ -f $O/conv.json ] && return; bash $W/tools/conv_only.sh $W/$k $id $O; }
export -f run; export W
( for id in $(cat res/convn.lst); do echo "kitnp8 $id"; done ) | xargs -P 9 -L 1 bash -c 'run $0 $1'
/opt/conv/env/bin/python tools/cvsum2.py kitn kitnp8 > res/convn8_sum.txt 2>&1; aws s3 cp --quiet res/convn8_sum.txt $OUT/final/convn8_sum.txt
/opt/conv/env/bin/python tools/cvsum2.py kitnp kitnp8 > res/convnp8_sum.txt 2>&1; aws s3 cp --quiet res/convnp8_sum.txt $OUT/final/convnp8_sum.txt
echo C8DONE
