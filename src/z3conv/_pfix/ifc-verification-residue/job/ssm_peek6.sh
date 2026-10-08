#!/bin/bash
W=/work/agentwork/ifc-verification-residue
python3 -c "
import json
rs=[json.loads(l) for l in open('$W/diag/iter_seaport_c500.jsonl')]
print('chunked', len(rs))
for r in rs[::max(1,len(rs)//10)]+rs[-2:]: print(r)
"
for f in $W/diag/probe_seaport_*.jsonl; do python3 -c "
import json,sys
rs=[json.loads(l) for l in open('$f')]
ks=[r for r in rs if 'k' in r]
print('$f'.split('/')[-1], 'n', len(ks), 'last k', ks[-1]['k'] if ks else None, 'maxrss', max([r['rss_mb'] for r in ks] or [0]), [r for r in rs if 'KILLED_AT' in r][:1], sorted(ks,key=lambda r:-r['sec'])[:1])
"; done
cat $W/wd.log 2>/dev/null | tail -5
free -g | head -2
