#!/bin/bash
# corpus convert-only: code-n + full cut patch (P1-P13) = kitnp5, compared with kitn (deployed code n) and kitnp (P1-P11)
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/*.py tools/ 2>/dev/null
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
until [ -f res/convn_sum.txt ]; do sleep 20; done
rm -rf kitnp5; cp -r kitn kitnp5; /opt/conv/env/bin/python stage/patch2/apply_cut_patch.py kitnp5 > res/patch_kitnp5.txt 2>&1 && touch kitnp5/.patched; tail -2 res/patch_kitnp5.txt
[ -f kitnp5/.patched ] || exit 1
md5sum kitnp5/db1old.py kitnp5/db1dec.py kitnp5/db1step.py kitnp5/fittings.py > res/kitnp5.md5
run() { k=$1; id=$2; O=$W/convall/$k/$id; [ -f $O/conv.json ] && return; bash $W/tools/conv_only.sh $W/$k $id $O; }
export -f run; export W
( for id in $(cat res/convn.lst); do echo "kitnp5 $id"; done ) | xargs -P 12 -L 1 bash -c 'run $0 $1'
/opt/conv/env/bin/python tools/cvsum2.py kitn kitnp5 > res/convn5_sum.txt 2>&1
/opt/conv/env/bin/python tools/cvsum2.py kitnp kitnp5 > res/convnp5_sum.txt 2>&1
for f in convn5_sum.txt convnp5_sum.txt patch_kitnp5.txt kitnp5.md5; do aws s3 cp --quiet res/$f $OUT/convn/$f; done
echo CONVN5DONE
