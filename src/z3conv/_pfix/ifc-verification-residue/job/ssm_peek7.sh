#!/bin/bash
W=/work/agentwork/ifc-verification-residue
sleep 45
python3 -c "
import json
rs=[json.loads(l) for l in open('$W/diag/iter_seaport_c500.jsonl')]
print('chunked', len(rs))
for r in rs[-8:]: print(r)
"
for p in $(pgrep -f "probe_iter.py"); do ps -o pid,rss,etimes,pcpu -p $p; done
cat $W/wd.log 2>/dev/null | tail -5
