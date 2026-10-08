#!/bin/bash
W=/work/agentwork/ifc-verification-residue
for i in $(seq 1 30); do
  n=0
  for f in $W/w/far_vr7/7ff7ad6bbfd82b26/case.json $W/w/stockton_vr7/2c0f7a89ddf2d595/case.json; do [ -f $f ] && n=$((n+1)); done
  [ $n -ge 2 ] && break
  sleep 10
done
for f in $W/w/far_vr7/7ff7ad6bbfd82b26/case.json $W/w/far_vr7F_gp/7ff7ad6bbfd82b26/case.json $W/w/stockton_vr7/2c0f7a89ddf2d595/case.json; do
python3 - $f <<'PY'
import json,sys
try: c=json.load(open(sys.argv[1]))
except Exception as e: print(sys.argv[1], 'pending'); sys.exit()
st=c.get('stats') or {}
print(sys.argv[1].split('/')[-3:-1], c.get('class'), c.get('issues'), [s['type']+':'+str(s['count']) for s in c.get('standins') or []], st.get('levels'), 'verify', {k:(st.get('verify') or {}).get(k) for k in ('sec','identical_parts_not_reverified')}, 'L0', st.get('verify_L0'), 'copies', st.get('instances_written_as_copies'), 'tot', st.get('total_sec'))
PY
done
