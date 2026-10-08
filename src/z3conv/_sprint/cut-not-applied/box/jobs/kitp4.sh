#!/bin/bash
# final patch (P1-P10) on the current S3 control kit (code l) and on the newer local code-m kit files when given; convert-only checks
W=/work/agentwork/cut-not-applied; cd $W
rm -rf kitp4; cp -r kit2 kitp4; rm -f kitp4/.patched
/opt/conv/env/bin/python stage/patch/apply_cut_patch.py kitp4 > res/patch_kitp4.txt 2>&1 && touch kitp4/.patched; cat res/patch_kitp4.txt
for id in 27a9febf9f71d956 cd9207295eb9bdfc 0762effe61de88c0 1d8972fb557e3371 4518a79a995bdee0; do
  ( bash tools/conv_only.sh $W/kitp4 $id $W/convall/kitp4/$id; python3 -c "
import json; c=json.load(open('$W/convall/kitp4/$id/convert.json')); print('$id', c.get('status'), 'skipped', {k: v for k, v in (c.get('skipped') or {}).items() if 'cut' in k}, 'applied', c.get('cuts_applied'), 'written', c.get('written'))" ) &
done; wait
