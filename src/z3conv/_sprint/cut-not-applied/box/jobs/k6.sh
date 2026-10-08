#!/bin/bash
# final kit (code n + P1-P14) = kitnp6: a944 trace (P14), p7.64 pipelines without / with fittings (P12 renders)
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/*.py stage/tools/*.sh tools/ 2>/dev/null
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
rm -rf kitnp6; cp -r kitn kitnp6; /opt/conv/env/bin/python stage/patch2/apply_cut_patch.py kitnp6 > res/patch_kitnp6.txt 2>&1 && touch kitnp6/.patched; tail -1 res/patch_kitnp6.txt
[ -f kitnp6/.patched ] || exit 1
md5sum kitnp6/db1old.py kitnp6/db1dec.py kitnp6/db1step.py kitnp6/fittings.py > res/kitnp6.md5; aws s3 cp --quiet res/kitnp6.md5 $OUT/final/
ln -sf $W/fit/p7.64.db1 src/fit_p7.64.db1
( timeout 2400 /opt/conv/ifc84/bin/python tools/trace_unbuilt2.py kitnp6 src/a94442572f225f50.db1 > res/trace6_a944.txt 2>&1; aws s3 cp --quiet res/trace6_a944.txt $OUT/final/ ) &
( timeout 3000 /opt/conv/ifc84/bin/python tools/trace_unbuilt2.py kitnp6 src/2ffffe4d1d7811e9.db1 > res/trace6_2fff.txt 2>&1; aws s3 cp --quiet res/trace6_2fff.txt $OUT/final/ ) &
run_one() { v=$1; id=$2; O=$W/pipes4/$v/$id; [ -f $O/pipe.json ] && return
  if [ "$v" = nofit ]; then DB1_FITTINGS=0 bash $W/tools/pipe.sh $W/kitnp6 $id $O; else bash $W/tools/pipe.sh $W/kitnp6 $id $O; fi; echo "done $v $id"; }
export -f run_one; export W
printf "nofit fit_p7.64\nfit fit_p7.64\nnofit a94442572f225f50\nfit a94442572f225f50\n" | xargs -P 4 -L 1 bash -c 'run_one $0 $1'
wait
echo K6DONE
