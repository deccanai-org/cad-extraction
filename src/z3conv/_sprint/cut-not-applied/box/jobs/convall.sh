#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
until [ -f kitp3/.patched ]; do sleep 10; done
ls -S src/*.db1 | grep -v truth_ | xargs -n1 basename | sed 's/.db1$//' | tac > res/convall.lst
run() { k=$1; id=$2; O=$W/convall/$k/$id; [ -f $O/conv.json ] && return; bash $W/tools/conv_only.sh $W/$k $id $O; }
export -f run; export W
( for id in $(cat res/convall.lst); do echo "kit2 $id"; echo "kitp3 $id"; done ) | xargs -P 4 -L 1 bash -c 'run $0 $1'
tar czf res/convall.tgz convall --exclude=model.ifc; aws s3 cp --quiet res/convall.tgz $OUT/convall/convall.tgz
echo CONVALLDONE
