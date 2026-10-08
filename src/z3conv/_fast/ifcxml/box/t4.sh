#!/bin/bash
# reference samples: ifc2step6 on the ifcxml2spf SPF vs ifc2step6's built-in ifcXML reader on the raw file (same census)
cd /work/agentwork/ifcxml/t2
P=/opt/conv/env/bin/python; K=/work/agentwork/ifcxml/kit
export DEFLECTION=0.005 ANG_DEFLECTION=0.6
mkdir -p work/t4
for n in Tests__TestSourceFiles__4walls1floorSite.ifcxml Tests__TestFiles__HelloWallXml.ifczip ifcopenshell_files__wall-with-opening-and-window.ifcxml ifcopenshell_files__wall-with-opening-and-window_ifcxml_format.ifczip Tests__TestFiles__IkeaKitchenCabinets.ifcXML Tests__TestFiles__Dimensions.ifcxml; do
  spf=work/tests/$n.ifc; raw=tests/external/$n; o=work/t4/$n
  [ -f $spf ] || continue
  $P $K/ifc_census.py $spf $o.census.json --parts $o.src.jsonl.gz > $o.census.log 2>&1
  for t in spf raw; do
    in=$spf; [ $t = raw ] && in=$raw
    timeout 900 $P $K/ifc2step6.py $in $o.$t.step --mode hybrid --prec 2 --threads 2 > $o.$t.log 2>&1; rc=$?
    $P $K/step_check.py $o.$t.step $o.$t.check.json --parts $o.$t.parts.jsonl.gz > $o.$t.check.log 2>&1
    $P $K/grade_join.py $o.src.jsonl.gz $o.$t.parts.jsonl.gz $o.$t.join.json > /dev/null 2>&1
    $P - "$o" "$t" "$rc" <<'PY'
import json, sys
o, t, rc = sys.argv[1:4]
def j(p):
    try: return json.load(open(p))
    except Exception: return {}
st = j(o + '.' + t + '.step.stats.json'); ck = j(o + '.' + t + '.check.json'); jn = j(o + '.' + t + '.join.json'); cs = j(o + '.census.json')
print(json.dumps({'sample': o.rsplit('/', 1)[-1], 'route': t, 'rc': int(rc), 'census_by_category': cs.get('by_category'), 'parts': st.get('parts'),
                  'input_fix': st.get('input_fix'), 'solids': ck.get('solids'), 'matched': jn.get('matched'), 'coverage': (jn.get('coverage') or {}).get('all'),
                  'volume_within_5pct': (jn.get('volume') or {}).get('within_5pct'), 'volume_checked': (jn.get('volume') or {}).get('checked')}))
PY
  done
done > work/t4/summary.jsonl
aws s3 cp work/t4/summary.jsonl s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifcxml/reader_compare_samples.jsonl --only-show-errors
cat work/t4/summary.jsonl
