#!/bin/bash
cd /work/agentwork/cut-not-applied
for d in pipes2/*/*; do s=$(cat $d/pipe.json 2>/dev/null | cut -c1-150); st=$(python3 -c "import json;print(json.load(open('$d/convert.json')).get('status'))" 2>/dev/null); echo "$d conv=$st $s"; done
tail -5 logs/kitp3.log
