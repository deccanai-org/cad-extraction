#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/step_check_far.py $W/job/step_check_far.py
cp $W/job/step_check_far.py $W/kit_gp/step_check.py
cd $W/diag/gp
P=/opt/conv/env/bin/python
for d in mnc_dev3/c13135ba64e2e8fd far2_pfixB_gp/c13135ba64e2e8fd far2_pfixB_gp/4f6b8e2e96937507 mnc_dev3/d9962a0cdfd33ee0; do
  S=$W/w/$d/out.step; n=$(echo $d | tr '/' '_')
  timeout 300 $P $W/job/step_check_far.py $S $n.far2.json --parts $n.far2.parts.jsonl.gz > /dev/null 2>&1
  python3 -c "
import json
a=json.load(open('$n.stock.json')); b=json.load(open('$n.far2.json'))
k=('transferred','solids','valid','invalid','nonpos_vol','faces')
print('$d', 'stock', {x:a.get(x) for x in k}, '| far', {x:b.get(x) for x in k}, 'off', b.get('translated_for_check_mm'), 'bbox_equal', a.get('bbox')==b.get('bbox'), b.get('bbox'))
"
done
