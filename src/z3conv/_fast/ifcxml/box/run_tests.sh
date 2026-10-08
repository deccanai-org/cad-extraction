#!/bin/bash
# regression: every external ifcXML / ifcZIP sample -> ifcxml2spf -> validate_spf (+ compare_sibling where an
# independent SPF export of the same model exists)
cd "$(dirname "$0")"
P=/opt/conv/env/bin/python
mkdir -p work/tests
for f in tests/external/*; do
  b=$(basename "$f"); n=$b
  case "$b" in *.ifc) continue;; esac
  $P ifcxml2spf.py "$f" work/tests/$n.ifc --report work/tests/$n.report.json > work/tests/$n.conv.out 2>&1
  rc=$?
  echo "== $b rc=$rc $(head -c 300 work/tests/$n.conv.out)"
  if [ -f work/tests/$n.ifc ]; then
    $P validate_spf.py "$f" work/tests/$n.ifc --conv-report work/tests/$n.report.json --report work/tests/$n.validate.json 2>&1 | head -c 900; echo
  fi
done
# siblings: same model exported as SPF by the reference tools
cmp() { [ -f "work/tests/$1.ifc" ] && $P compare_sibling.py "work/tests/$1.ifc" "tests/external/$2" --report "work/tests/$1.sibling.json" | head -c 700; echo; }
echo "== sibling 4walls"; cmp Tests__TestSourceFiles__4walls1floorSite.ifcxml Tests__TestSourceFiles__4walls1floorSite.ifc
echo "== sibling wall"; cmp ifcopenshell_files__wall-with-opening-and-window.ifcxml bsst__wall-with-opening-and-window.ifc
$P - <<'PY'
import json, glob, os
rows = []
for r in sorted(glob.glob('work/tests/*.report.json')):
    n = os.path.basename(r)[:-12]
    c = json.load(open(r)); v = {}
    if os.path.exists('work/tests/%s.validate.json' % n):
        v = json.load(open('work/tests/%s.validate.json' % n))
    rows.append({'test': n, 'status': c.get('status'), 'reason': c.get('reason'), 'schema': c.get('schema'),
                 'instances': c.get('instances'), 'dangling': c.get('dangling_references'),
                 'unknown': c.get('unknown_xml_names'), 'value_errors': c.get('value_errors'),
                 'notes': list((c.get('notes') or {}).keys()),
                 'verdict': v.get('verdict'), 'xml_instance_elements': v.get('xml_instance_elements'),
                 'spf_instances': v.get('spf_instances'), 'roundtrip_failures': (v.get('roundtrip') or {}).get('failures'),
                 'roundtrip_counts': (v.get('roundtrip') or {}).get('counts'),
                 'schema_issues': (v.get('schema_validate') or {}).get('issues'),
                 'schema_issue_kinds': (v.get('schema_validate') or {}).get('by_kind')})
sib = {}
for r in glob.glob('work/tests/*.sibling.json'):
    d = json.load(open(r)); sib[os.path.basename(r)] = {k: d.get(k) for k in ('roots_conv', 'roots_sibling', 'common', 'only_sibling', 'relationships_compared', 'products_compared', 'placement_max_abs_diff', 'failures', 'samples', 'verdict')}
json.dump({'tests': rows, 'siblings': sib}, open('work/tests/summary.json', 'w'), indent=1)
print(json.dumps({'tests': len(rows), 'pass': sum(1 for r in rows if r['verdict'] == 'pass')}))
PY
