#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
for n in gsk iron; do ln -sf $W/truth/$n.db1 src/truth_$n.db1; done
run_one() {
  v=$1; id=$2; O=$W/pipes2/$v/$id
  [ -f $O/pipe.json ] && return
  k=$v; [ "$v" = nc ] && k=kitp2
  if [ "$v" = nc ]; then DB1_PART_CUTS=0 bash $W/tools/pipe.sh $W/$k $id $O; else bash $W/tools/pipe.sh $W/$k $id $O; fi
  echo "done $v $id $(cat $O/pipe.json)"
}
export -f run_one; export W
printf "kit2 truth_gsk\nkitp2 truth_gsk\nnc truth_gsk\nkit2 truth_iron\nkitp2 truth_iron\nnc truth_iron\n" | xargs -P 3 -L 1 bash -c 'run_one $0 $1'
for n in gsk iron; do /opt/conv/env/bin/python tools/truth_cmp.py $n > res/truth_$n.txt 2>&1; aws s3 cp --quiet res/truth_$n.txt $OUT/truth/; done
echo TRUTHDONE
