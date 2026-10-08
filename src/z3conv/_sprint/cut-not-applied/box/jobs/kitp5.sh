#!/bin/bash
# final patch P1-P11 on the S3 control kit; convert-only functional check on old / new engines
W=/work/agentwork/cut-not-applied; cd $W
rm -rf kitp5; cp -r kit2 kitp5; rm -f kitp5/.patched
/opt/conv/env/bin/python stage/patch/apply_cut_patch.py kitp5 > res/patch_kitp5.txt 2>&1 && touch kitp5/.patched; tail -1 res/patch_kitp5.txt
for id in 0762effe61de88c0 1d8972fb557e3371 6eabb07e71459be6 a94442572f225f50 e151a8faacbce446; do
  ( bash tools/conv_only.sh $W/kitp5 $id $W/convall/kitp5/$id; python3 -c "
import json; c=json.load(open('$W/convall/kitp5/$id/convert.json')); print('$id', c.get('status'), 'cut_stats', c.get('cut_stats'), 'skipped', {k: v for k, v in (c.get('skipped') or {}).items() if 'cut' in k}, 'written', c.get('written'))" ) &
done; wait
