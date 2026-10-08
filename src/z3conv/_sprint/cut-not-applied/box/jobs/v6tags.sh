#!/bin/bash
cd /work/agentwork/cut-not-applied
for d in pipes2/kit2/* pipes2/kitp2/* pipes2/kitp3/*; do
  [ -f $d/model.stp.stats.json ] || continue
  python3 - "$d" <<'P'
import json, sys
d = sys.argv[1]; s = json.load(open(d + '/model.stp.stats.json'))
j = json.load(open(d + '/join.json')) if __import__('os').path.exists(d + '/join.json') else {}
print(d, 'tags', s.get('tags'), 'levels', s.get('levels'), 'surface_fallback', s.get('surface_fallback_parts'), 'join cov', (j.get('coverage') or {}).get('all'), 'surface_parts', j.get('surface_parts'), 'missing', (j.get('missing_examples') or [])[:2])
P
done
