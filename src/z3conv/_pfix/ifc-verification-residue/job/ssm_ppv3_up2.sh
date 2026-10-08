#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-verification-residue/ppv_vr3
for i in beeeacea7d2d7546 2bcaa3013d9250c2; do
  d=$W/w/ppv_vr3/$i
  if [ -f $d/case.json ]; then
    for fn in case.json out.step.stats.json out.step.check.json census.json; do [ -f $d/$fn ] && aws s3 cp --quiet $d/$fn $R/$i/$fn; done
    python3 -c "
import json; c=json.load(open('$d/case.json')); st=c.get('stats') or {}
print('$i', c.get('class'), c.get('issues'), [s['type']+':'+str(s['count']) for s in c.get('standins') or []], 'MB', round((st.get('out_bytes') or 0)/1e6,1), st.get('levels'), 'graded', c.get('graded_by'))"
  else echo "$i pending"; fi
done
