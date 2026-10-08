#!/bin/bash
cd /work/agentwork/cut-not-applied; export PIPE_A=pipes2/kit2 PIPE_B=pipes2/kitp2
/opt/conv/env/bin/python tools/pipe_cmp.py 4518a79a995bdee0 7c82c44be6c7ae3f 2>&1 | python3 -c "
import sys, json
for l in sys.stdin:
    if not l.startswith('{'): print(l[:300]); continue
    r = json.loads(l); print(r['id'], {k: r[k] for k in ('written','cuts_applied','cut_body_unbuilt','solids','invalid','nonpos','join_cov','step_sec','phantom_parts_no_longer_steel','phantom_kg','removed_kg','parents_material_removed','parents_cut_no_effect','parents_volume_grew','steel_kg')})"
for v in kit2 kitp2; do python3 -c "
import json; s=json.load(open('pipes2/$v/4518a79a995bdee0/model.stp.stats.json')); print('$v', s.get('tags'))"; done
