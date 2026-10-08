#!/bin/bash
W=/work/agentwork/ifc-verification-residue
cd $W/diag/gp
P=/opt/conv/env/bin/python
for d in mnc_dev3/c951cd2d377ddbd0 mnc_dev3/d9962a0cdfd33ee0 mnc_dev3/7ff7ad6bbfd82b26 mnc_dev3/4f6b8e2e96937507; do
  S=$W/w/$d/out.step; n=$(echo $d | tr '/' '_')
  [ -f $n.stock.json ] || timeout 300 $P $W/kit/step_check.py $S $n.stock.json --parts $n.stock.parts.jsonl.gz > /dev/null 2>&1
  timeout 300 $P $W/job/step_check_far.py $S $n.far3.json --parts $n.far3.parts.jsonl.gz > /dev/null 2>&1
  python3 -c "
import json
a=json.load(open('$n.stock.json')); b=json.load(open('$n.far3.json'))
k=('transferred','solids','valid','invalid','nonpos_vol','faces')
print('$d', 'stock', {x:a.get(x) for x in k}, '| far-rule', {x:b.get(x) for x in k}, b.get('far_check'), 'bbox_equal', a.get('bbox')==b.get('bbox'))
"
done
