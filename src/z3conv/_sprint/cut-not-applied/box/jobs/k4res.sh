#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W; cat res/patch_kitp4.txt; ls convall/kitp4/
for id in 27a9febf9f71d956 cd9207295eb9bdfc 0762effe61de88c0 1d8972fb557e3371 4518a79a995bdee0; do python3 -c "
import json; c=json.load(open('$W/convall/kitp4/$id/convert.json')); print('$id', c.get('status'), 'skipped', {k: v for k, v in (c.get('skipped') or {}).items() if 'cut' in k}, 'applied', c.get('cuts_applied'), 'written', c.get('written'))" 2>&1 | tail -1; done
