#!/bin/bash
# P13 (old-engine fittings / line cuts) vs Tekla's own IFC: full worker pipeline, kitnp4 with DB1_FITTINGS=0 vs =1
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/*.py stage/tools/*.sh tools/ 2>/dev/null
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
rm -rf kitnp4; cp -r kitn kitnp4; /opt/conv/env/bin/python stage/patch2/apply_cut_patch.py kitnp4 > res/patch_kitnp4.txt 2>&1 && touch kitnp4/.patched; tail -2 res/patch_kitnp4.txt
[ -f kitnp4/.patched ] || exit 1
for n in gambro; do ln -sf $W/truth/$n.db1 src/truth_$n.db1; done
run_one() { v=$1; id=$2; O=$W/pipes3/$v/$id; [ -f $O/pipe.json ] && return
  if [ "$v" = nofit ]; then DB1_FITTINGS=0 bash $W/tools/pipe.sh $W/kitnp4 $id $O; else bash $W/tools/pipe.sh $W/kitnp4 $id $O; fi; echo "done $v $id $(cat $O/pipe.json)"; }
export -f run_one; export W
printf "nofit truth_iron\nfit truth_iron\nnofit truth_gsk\nfit truth_gsk\nnofit 0762effe61de88c0\nfit 0762effe61de88c0\n" | xargs -P 5 -L 1 bash -c 'run_one $0 $1'
for n in iron gsk; do KIT=$W/kitnp4 /opt/conv/env/bin/python tools/truth_cmp2.py $n nofit=pipes3/nofit/truth_$n fit=pipes3/fit/truth_$n > res/truth13_$n.txt 2>&1; aws s3 cp --quiet res/truth13_$n.txt $OUT/truth13/; done
for v in nofit fit; do python3 -c "
import json; c=json.load(open('pipes3/$v/0762effe61de88c0/convert.json')); print('$v', 'written', c.get('written'), 'cuts_applied', c.get('cuts_applied'), 'fittings', c.get('fittings'), 'skipped', c.get('skipped'))"; done > res/p13_0762.txt
aws s3 cp --quiet res/p13_0762.txt $OUT/truth13/
printf "nofit truth_gambro\nfit truth_gambro\n" | xargs -P 2 -L 1 bash -c 'run_one $0 $1'
KIT=$W/kitnp4 /opt/conv/env/bin/python tools/truth_cmp2.py gambro nofit=pipes3/nofit/truth_gambro fit=pipes3/fit/truth_gambro > res/truth13_gambro.txt 2>&1; aws s3 cp --quiet res/truth13_gambro.txt $OUT/truth13/
echo TR13DONE
