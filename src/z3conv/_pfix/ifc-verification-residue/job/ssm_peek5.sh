#!/bin/bash
W=/work/agentwork/ifc-verification-residue
python3 -c "
import json
rs=[json.loads(l) for l in open('$W/diag/iter_seaport_t4.jsonl')]
print(len(rs))
for r in rs[::max(1,len(rs)//12)]+rs[-2:]: print(r)
"
echo ---single; python3 -c "
import json
rs=[json.loads(l) for l in open('$W/diag/probe_seaport.jsonl')]
ks=[r for r in rs if 'k' in r]; print('n', len(ks), 'last', ks[-1] if ks else None)
print([r for r in rs if 'KILLED_AT' in r])
big=sorted(ks, key=lambda r:-r.get('d_rss',0))[:3]; print(big)
"
free -g | head -2; uptime
