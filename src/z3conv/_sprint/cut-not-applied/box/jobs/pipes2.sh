#!/bin/bash
# current deployed kit (kit2 = S3 control copy now) vs kit2 + apply_cut_patch.py (kitp2); 'nc' = kitp2 with DB1_PART_CUTS=0 (gross)
W=/work/agentwork/cut-not-applied; cd $W
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
if [ ! -f kitp2/.patched ]; then
  rm -rf kit2 kitp2
  aws s3 sync --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/db1/ kit2/ --exclude hold --exclude canary.json --exclude env.json
  cp -r kit2 kitp2
  /opt/conv/env/bin/python stage/patch/apply_cut_patch.py kitp2 > res/patch_kitp2.txt 2>&1 && touch kitp2/.patched
  cat res/patch_kitp2.txt; grep -h "^CODE" kit2/worker.py
fi
[ -f kitp2/.patched ] || { echo "patch failed"; exit 1; }
cat > res/pipes2.lst <<'L'
kit2 0762effe61de88c0
kitp2 0762effe61de88c0
nc 0762effe61de88c0
kit2 9f619582d2424ed4
kitp2 9f619582d2424ed4
nc 9f619582d2424ed4
kit2 6304887153755ea3
kitp2 6304887153755ea3
nc 6304887153755ea3
kit2 e151a8faacbce446
kitp2 e151a8faacbce446
nc e151a8faacbce446
kit2 df81723c53d23ef7
kitp2 df81723c53d23ef7
nc df81723c53d23ef7
kit2 1d8972fb557e3371
kitp2 1d8972fb557e3371
kit2 6eabb07e71459be6
kitp2 6eabb07e71459be6
kit2 6a44b409f977d7c2
kitp2 6a44b409f977d7c2
nc 6a44b409f977d7c2
kit2 575da79b6096c760
kitp2 575da79b6096c760
nc 575da79b6096c760
kit2 4518a79a995bdee0
kitp2 4518a79a995bdee0
kit2 a94442572f225f50
kitp2 a94442572f225f50
kit2 7c82c44be6c7ae3f
kitp2 7c82c44be6c7ae3f
kit2 5b33936fcd1e3efc
kitp2 5b33936fcd1e3efc
kit2 dcdf359ef4a2499b
kitp2 dcdf359ef4a2499b
L
run_one() {
  v=$1; id=$2; O=$W/pipes2/$v/$id
  if [ -f $O/pipe.json ]; then return; fi
  k=$v; [ "$v" = nc ] && k=kitp2
  if [ "$v" = nc ]; then DB1_PART_CUTS=0 bash $W/tools/pipe.sh $W/$k $id $O; else bash $W/tools/pipe.sh $W/$k $id $O; fi
  for f in pipe.json convert.json check.json join.json model.png census.json; do
    [ -f $O/$f ] && aws s3 cp --quiet $O/$f $OUT/pipes2/$v/$id/$f
  done
  [ -f $O/convert.json.parts.json.gz ] && aws s3 cp --quiet $O/convert.json.parts.json.gz $OUT/pipes2/$v/$id/parts.json.gz
  [ -f $O/step_parts.jsonl.gz ] && aws s3 cp --quiet $O/step_parts.jsonl.gz $OUT/pipes2/$v/$id/step_parts.jsonl.gz
  echo "done $v $id $(cat $O/pipe.json)"
}
export -f run_one; export W OUT
cat res/pipes2.lst | xargs -P 5 -L 1 bash -c 'run_one $0 $1'
echo ALLDONE
