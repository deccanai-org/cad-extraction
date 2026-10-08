#!/bin/bash
W=/work/agentwork/ifc-verification-residue
python3 - <<'PY'
import json, collections
for d in ('ppv_vr4b/af3c44bd76cfb905', 'ppv_vr3/beeeacea7d2d7546'):
    P = json.load(open('/work/agentwork/ifc-verification-residue/w/%s/out.step.parts.json' % d))['parts']
    l4 = [p for p in P if p['level'] >= 3]
    print('==', d, len(l4), collections.Counter((p['cls'], p['src']) for p in l4).most_common(5))
    print('   why', collections.Counter(tuple(p['why']) for p in l4).most_common(4))
    print('   tags', collections.Counter(tuple(p['tags']) for p in l4).most_common(4))
    print('   ex', [(p['gid'], p['name'], p['faces']) for p in l4[:4]])
PY
