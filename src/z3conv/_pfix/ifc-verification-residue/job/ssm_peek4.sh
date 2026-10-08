#!/bin/bash
W=/work/agentwork/ifc-verification-residue
python3 -c "
import json
rs=[json.loads(l) for l in open('$W/diag/iter_seaport_t4.jsonl')]
print(len(rs))
for r in rs[::max(1,len(rs)//25)]+rs[-3:]: print(r)
"
tail -3 $W/diag/iter_seaport_t4.log
ps -o pid,rss,etimes,pcpu,args -p $(pgrep -f probe_iter.py | head -1) 2>/dev/null | cut -c1-100
free -g | head -2
