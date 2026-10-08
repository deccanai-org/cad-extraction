#!/bin/bash
# code-n kit (S3 control, deployed next) vs code-n + rebased cut patch: convert-only over the whole data-3 DB1 corpus
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/*.py stage/tools/*.sh tools/ 2>/dev/null
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
rm -rf kitn kitnp; mkdir -p kitn
aws s3 sync --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/db1/ kitn/ --exclude hold --exclude canary.json --exclude env.json --exclude 'fixes/*' --exclude 'v2/*'
grep -h "^CODE" kitn/worker.py; md5sum kitn/db1old.py kitn/db1dec.py kitn/db1step.py
cp -r kitn kitnp
/opt/conv/env/bin/python stage/patch2/apply_cut_patch.py kitnp > res/patch_kitnp.txt 2>&1 && touch kitnp/.patched; cat res/patch_kitnp.txt
[ -f kitnp/.patched ] || exit 1
ls src/*.db1 | grep -v truth_ | wc -l
ls -S src/*.db1 | grep -v truth_ | xargs -n1 basename | sed 's/.db1$//' > res/convn.lst
run() { k=$1; id=$2; O=$W/convall/$k/$id; [ -f $O/conv.json ] && return; bash $W/tools/conv_only.sh $W/$k $id $O; }
export -f run; export W
( for id in $(cat res/convn.lst); do echo "kitn $id"; echo "kitnp $id"; done ) | xargs -P 12 -L 1 bash -c 'run $0 $1'
/opt/conv/env/bin/python tools/cvsum2.py kitn kitnp > res/convn_sum.txt 2>&1
aws s3 cp --quiet res/convn_sum.txt $OUT/convn/convn_sum.txt; aws s3 cp --quiet res/patch_kitnp.txt $OUT/convn/patch_kitnp.txt
echo CONVNDONE
