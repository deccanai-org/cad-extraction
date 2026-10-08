#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/step_check_far.py $W/job/step_check_far.py
cp $W/job/step_check_far.py $W/kit_gp/step_check.py
mkdir -p $W/diag/gp; cd $W/diag/gp
P=/opt/conv/env/bin/python
for d in mnc_dev3/c951cd2d377ddbd0 mnc_dev3/d9962a0cdfd33ee0 mnc_dev3/4f6b8e2e96937507 mnc_dev3/c13135ba64e2e8fd far2_pfixB_gp/c13135ba64e2e8fd far2_pfixB_gp/4f6b8e2e96937507 far2_pfixB_gp/700b4c5c15d6f19e far2_pfixB_gp/6f3ceef9bdcb1a56 mnc_dev3/4bbcc615d753f653; do
  S=$W/w/$d/out.step; [ -f $S ] || { echo "missing $S"; continue; }
  n=$(echo $d | tr '/' '_')
  timeout 900 $P $W/kit/step_check.py $S $n.stock.json --parts $n.stock.parts.jsonl.gz > /dev/null 2>&1
  timeout 900 $P $W/job/step_check_far.py $S $n.far.json --parts $n.far.parts.jsonl.gz > /dev/null 2>&1
  python3 -c "
import json
a=json.load(open('$n.stock.json')); b=json.load(open('$n.far.json'))
k=('roots','transferred','solids','valid','invalid','nonpos_vol','empty_roots','faces')
print('$d', 'stock', {x:a.get(x) for x in k}, '| far', {x:b.get(x) for x in k}, 'off', b.get('translated_for_check_mm'), 'bbox same', a.get('bbox')==b.get('bbox'), a.get('bbox'), b.get('bbox'))
"
done
