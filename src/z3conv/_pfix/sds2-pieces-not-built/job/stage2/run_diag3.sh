#!/bin/bash
W=/work/agentwork/sds2-pieces-not-built; cd $W
C=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-pieces-not-built
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-pieces-not-built/diag3
for f in diag3.py diag3_list.txt trees553.tgz; do aws s3 cp --quiet $C/$f $W/stage/$f; done
rm -rf $W/trees/v553 $W/trees/v553p && tar xzf $W/stage/trees553.tgz -C $W/trees
mkdir -p out/diag3
one() {
  id=$1; key=$2
  name=$(/opt/conv/env/bin/python $W/stage/fetch_one.py $W/jobs $id 16 2>>out/diag3/fetch.err | tail -1)
  aws s3 cp --quiet "$key" out/diag3/$name.skipped.csv
  for V in v553 v553p; do
    timeout 2400 $W/env/bin/python $W/stage/diag3.py $W/trees/$V/decode $W/jobs/$name out/diag3/$name.skipped.csv out/diag3/$name.$V.json > out/diag3/$name.$V.log 2>&1
    aws s3 cp --quiet out/diag3/$name.$V.json $OUT/$name.$V.json; aws s3 cp --quiet out/diag3/$name.$V.log $OUT/$name.$V.log
  done
}
export -f one; export W OUT
cat $W/stage/diag3_list.txt | xargs -P 6 -L 1 bash -c 'one "$0" "$1"'
echo done > out/diag3/DONE; aws s3 cp --quiet out/diag3/DONE $OUT/DONE
