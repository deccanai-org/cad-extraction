#!/bin/bash
# recover parameters, then verify (source + delivered) for every model, smallest first
cd "$(dirname "$0")/.."
PY=../venv/bin/python
$PY - <<'P' > /tmp/plist.$$
import json, os
M = json.load(open('models.json'))
M.sort(key=lambda m: os.path.getsize(m['step_local']))
for m in M: print('\t'.join([m['stem'], m['step_local'], m['ifc_local']]))
P
while IFS=$'\t' read stem step ifc; do
  s=$(date +%s)
  [ -f "out/$stem/recover_summary.json" ] || $PY tools/recover.py "out/$stem" --jobs 9 > "out/$stem/recover.log" 2>&1
  $PY tools/verify.py "out/$stem" "$step" --ifc "$ifc" --jobs 9 > "out/$stem/verify.log" 2>&1
  echo "$(date +%H:%M:%S) $stem $(($(date +%s)-s))s rec=$(cat out/$stem/recover_summary.json 2>/dev/null | tr -d '\n ') $(python3 -c "import json;d=json.load(open('out/$stem/verification_summary.json'));print(d['parts'],d['status'],'src',d['source_check'],'notbuilt',d['delivered_parts_not_built'])" 2>&1 | tail -1)" >> pipeline_all.log
done < /tmp/plist.$$
echo ALLDONE >> pipeline_all.log
