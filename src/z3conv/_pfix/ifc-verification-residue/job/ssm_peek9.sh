#!/bin/bash
W=/work/agentwork/ifc-verification-residue
python3 -c "
import json
rs=[json.loads(l) for l in open('$W/diag/iter_seaport_c500.jsonl')]
print('chunked', len(rs), rs[-1], 'max', max(r.get('rss_mb',0) for r in rs))
"
tail -c 1500 $W/w/mnc_dev3/d713eae4bf9dd247/log.txt
ps -eo pid,rss,etimes,pcpu,args | grep -E "d713eae4|probe_" | grep -v grep | cut -c1-150
cat $W/wd.log 2>/dev/null | tail -3; uptime
