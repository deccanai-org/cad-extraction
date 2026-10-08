#!/bin/bash
# e2e.sh KIT ID : decode (convert_one) -> ifc2step5 hybrid prec 2 -> step_check (OCC) -> ifc_census -> grade_join, like worker.process
set -u
D=/Users/dhiren/Downloads/Deccan/z3conv/_deepdive/db1-axis-guard-cuts-versions
KIT=$D/$1; ID=$2
PY84=/Users/dhiren/Downloads/Deccan/cad-db1-convert/venv/bin/python
PYOCC=/Users/dhiren/Downloads/Deccan/z3conv/db1_v2/_env/env/bin/python
SRC=$(ls $D/src_db1/$ID*.db1); FULL=$(basename $SRC .db1)
W=$D/e2e/$1/${ID}; mkdir -p $W
echo null > $W/layout.json
$PY84 -c "import json; L=json.load(open('$KIT/layouts.json')); json.dump([v['layout'] for v in L.values() if v.get('layout')], open('$W/variants.json','w'))"
$PY84 $KIT/convert_one.py $SRC $W/model.ifc $KIT/tekla_profiles.json $W/layout.json $W/convert.json $W/variants.json > $W/log.txt 2>&1
$PY84 $KIT/ifc2step5.py $W/model.ifc $W/model.stp --mode hybrid --prec 2 --threads 2 >> $W/log.txt 2>&1
echo "step rc $?" >> $W/log.txt
$PYOCC $KIT/step_check.py $W/model.stp $W/check.json --parts $W/step_parts.jsonl.gz >> $W/val.log 2>&1
$PYOCC $KIT/ifc_census.py $W/model.ifc $W/census.json --parts $W/src_parts.jsonl.gz >> $W/census.log 2>&1
$PYOCC -c "
import sys, json; sys.path.insert(0, '$KIT'); import grade_join
j = grade_join.join(grade_join.load('$W/src_parts.jsonl.gz'), grade_join.load('$W/step_parts.jsonl.gz'))
json.dump(j, open('$W/join.json', 'w'), default=str)
c = json.load(open('$W/convert.json')); v = json.load(open('$W/check.json'))
print('$1', '$ID', 'axis_dropped', c.get('axis_mismatch_dropped'), 'written', c.get('written'), 'skipped', c.get('skipped'), 'cuts_applied', c.get('cuts_applied'),
      '| step solids', v.get('solids'), 'valid', v.get('valid'), 'invalid', v.get('invalid'), 'nonpos', v.get('nonpos_vol'), 'invalid_ex', v.get('invalid_examples'),
      '| join cov', j.get('coverage'), 'vol', {k: j.get('volume', {}).get(k) for k in ('checked', 'outside_5pct', 'median')})
"
