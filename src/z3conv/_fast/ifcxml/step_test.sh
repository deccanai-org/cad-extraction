#!/bin/bash
# STEP pipeline test of converted SPFs with the fleet runtime (python 3.11, ifcopenshell 0.9.0, pythonocc 8.0.1) and the
# kit files as published in s3://annotationprod/cad-disk-extract/_control/z3conv/ifc/ (snapshot in kit_snapshot/):
#   ifc_census.py (source inventory) -> ifc2step5.py|ifc2step6.py --mode hybrid --prec 2 -> step_check.py (OCC read-back)
#   -> grade_join.py (coverage by GlobalId + per-part volume vs source)
# usage: step_test.sh <conv: 5|6> <spf> [<spf> ...]
cd /Users/dhiren/Downloads/Deccan/z3conv/_fast/ifcxml
KPY=/Users/dhiren/Downloads/Deccan/z3conv/ifc_v6/_env/env/bin/python
export PYTHONDONTWRITEBYTECODE=1 DEFLECTION=0.005 ANG_DEFLECTION=0.6
V=$1; shift
for spf in "$@"; do
  s=$(basename "$spf" .ifc); o=step/$s.v$V
  echo "== $(date +%T) $s v$V"
  [ -f step/$s.census.json ] || $KPY kit_snapshot/ifc_census.py "$spf" step/$s.census.json --parts step/$s.src_parts.jsonl.gz > step/$s.census.log 2>&1
  /usr/bin/time -l $KPY kit_snapshot/ifc2step$V.py "$spf" $o.step --mode hybrid --prec 2 --threads 2 $EXTRA > $o.log 2>&1
  echo "convert rc=$?"
  /usr/bin/time -l $KPY kit_snapshot/step_check.py $o.step $o.check.json --png $o.png --parts $o.step_parts.jsonl.gz --title "$s v$V" > $o.check.log 2>&1
  echo "check rc=$?"
  $KPY kit_snapshot/grade_join.py step/$s.src_parts.jsonl.gz $o.step_parts.jsonl.gz $o.join.json > $o.join.log 2>&1
  echo "join rc=$?"
  python3 - "$o" "step/$s" <<'PY'
import json, sys
o, s = sys.argv[1], sys.argv[2]
st = json.load(open(o + '.step.stats.json'))
ck = json.load(open(o + '.check.json'))
cs = json.load(open(s + '.census.json'))
jn = json.load(open(o + '.join.json'))
print(json.dumps({'parts': st.get('parts'), 'faces': st.get('faces'), 'bbox': st.get('bbox'), 'total_sec': st.get('total_sec'),
  'census': {k: cs.get(k) for k in ('with_body', 'products', 'by_category', 'schema') if k in cs},
  'check': {k: ck.get(k) for k in ('roots', 'solids', 'invalid_solids', 'nonpositive_volume', 'bbox', 'blank', 'readback') if k in ck},
  'join': {k: jn.get(k) for k in ('mode', 'expected', 'matched', 'coverage', 'volume', 'step_parts_unmatched') if k in jn}})[:2500])
PY
done
echo STEPDONE
