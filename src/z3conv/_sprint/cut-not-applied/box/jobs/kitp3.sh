#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W
if [ ! -f kitp3/.patched ]; then rm -rf kitp3; cp -r kit2 kitp3; rm -f kitp3/.patched
  /opt/conv/env/bin/python stage/patch/apply_cut_patch.py kitp3 > res/patch_kitp3.txt 2>&1 && touch kitp3/.patched; cat res/patch_kitp3.txt; fi
run_one() {
  v=$1; id=$2; O=$W/pipes2/$v/$id; [ -f $O/pipe.json ] && return
  bash $W/tools/pipe.sh $W/$v $id $O; echo "done $v $id $(cat $O/pipe.json)"
}
export -f run_one; export W
printf "kitp3 e151a8faacbce446\nkitp3 575da79b6096c760\n" | xargs -P 2 -L 1 bash -c 'run_one $0 $1'
echo P3DONE
