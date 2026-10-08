#!/bin/bash
# full pipeline, deployed kit vs patched kit, on the test set (4 pipelines at a time, ~4-5 threads each)
W=/work/agentwork/cut-not-applied; cd $W
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
rm -rf kitp; cp -r kit kitp; cp stage/kitp/* kitp/
IDS="0762effe61de88c0 9f619582d2424ed4 6304887153755ea3 e151a8faacbce446 df81723c53d23ef7 6eabb07e71459be6 6a44b409f977d7c2 575da79b6096c760 7c82c44be6c7ae3f 5b33936fcd1e3efc"
for id in $IDS; do for k in kit kitp; do echo "$k $id"; done; done > res/pipes1.lst
run_one() {
  k=$1; id=$2; O=$W/pipes/$k/$id
  if [ -f $O/pipe.json ]; then return; fi
  bash $W/tools/pipe.sh $W/$k $id $O
  for f in pipe.json convert.json check.json join.json model.png census.json; do
    [ -f $O/$f ] && aws s3 cp --quiet $O/$f $OUT/pipes/$k/$id/$f
  done
  [ -f $O/convert.json.parts.json.gz ] && aws s3 cp --quiet $O/convert.json.parts.json.gz $OUT/pipes/$k/$id/parts.json.gz
  [ -f $O/step_parts.jsonl.gz ] && aws s3 cp --quiet $O/step_parts.jsonl.gz $OUT/pipes/$k/$id/step_parts.jsonl.gz
  echo "done $k $id $(cat $O/pipe.json)"
}
export -f run_one; export W OUT
cat res/pipes1.lst | xargs -P 4 -L 1 bash -c 'run_one $0 $1'
echo ALLDONE
