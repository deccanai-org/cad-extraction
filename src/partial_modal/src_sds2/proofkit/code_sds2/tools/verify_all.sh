#!/bin/bash
# verify every model (smallest first); one line per model into verify_all.log
cd "$(dirname "$0")/.."
PY=../venv/bin/python
$PY - <<'P' > /tmp/vlist.$$
import json, os
M = json.load(open('models.json'))
M.sort(key=lambda m: os.path.getsize(m['step_local']))
for m in M: print(m['stem'] + '\t' + m['step_local'])
P
while IFS=$'\t' read stem step; do
  s=$(date +%s)
  $PY tools/verify.py "out/$stem" "$step" --jobs 9 > "out/$stem/verify.log" 2>&1
  echo "$(date +%H:%M:%S) $stem $(($(date +%s)-s))s $(python3 -c "import json;d=json.load(open('out/$stem/verification_summary.json'));print(d['parts'],d['status'],'not_built',d['delivered_parts_not_built'])" 2>&1 | tail -1)" >> verify_all.log
done < /tmp/vlist.$$
echo ALLDONE >> verify_all.log
