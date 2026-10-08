#!/bin/bash
W=/work/agentwork/ifc-verification-residue
python3 -c "
import json
rs=[json.loads(l) for l in open('$W/diag/iter_seaport_c500.jsonl')]
print('chunked', len(rs)); print(rs[-1])
mx=max(rs,key=lambda r:r.get('rss_mb',0)); print('max', mx)
"
ls -la $W/diag/l2ev/; for f in $W/diag/l2ev/*.log; do tail -2 $f; done
cat $W/wd.log 2>/dev/null | tail -3
