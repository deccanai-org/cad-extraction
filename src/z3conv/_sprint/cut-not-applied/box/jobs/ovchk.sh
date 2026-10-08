#!/bin/bash
cd /work/agentwork/cut-not-applied
/opt/conv/env/bin/python - <<'P'
import json, hashlib
ov = json.load(open('kitp3/tekla_profiles_overlay.json'))
for i in ('4fa8f263f754f862', 'cc9bf730baa1585c'):
    h = hashlib.sha256(open(f'src/{i}.db1', 'rb').read()).hexdigest()
    pm = (ov.get('per_model') or {}).get(h) or {}
    print(i, h[:16], 'per_model entries', len(pm), [k for k in pm if 'R.B' in k], [hex(ord(c)) for c in [k for k in pm if 'R.B' in k][0]] if any('R.B' in k for k in pm) else None)
P
grep -o "unresolved_top[^]]*]" convall/kitp3/4fa8f263f754f862/convert.json | head -2
python3 -c "
import json; c=json.load(open('convall/kitp3/4fa8f263f754f862/convert.json')); print(c.get('unresolved_top')[:5]); print([hex(ord(x)) for x in c['unresolved_top'][0][0]])"
