#!/bin/bash
W=/work/agentwork/ifc-verification-residue
sleep 75
tail -3 $W/diag/probe_seaport_v1820.jsonl
python3 -c "
import json
rs=[json.loads(l) for l in open('$W/diag/iter_seaport_c500.jsonl')]
print('chunked', len(rs), rs[-1], 'max', max(r.get('rss_mb',0) for r in rs))
"
ps -eo pid,rss,etimes,args | grep -E "probe_" | grep -v grep | awk '{print $1, $2, $3}'
cat $W/wd.log 2>/dev/null | tail -3
