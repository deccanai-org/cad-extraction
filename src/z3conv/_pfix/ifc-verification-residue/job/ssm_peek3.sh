#!/bin/bash
W=/work/agentwork/ifc-verification-residue
cat $W/diag/far6_*.jsonl 2>/dev/null | python3 -c "
import json,sys
for l in sys.stdin:
    r=json.loads(l)
    for k in ('tc','kernel_poly','kernel_tri'):
        v=r.get(k)
        if isinstance(v,dict):
            print(r['gid'], r['name'], k, 'in_place', v['in_place']['verdict'], v['in_place']['brepcheck'], '| shifted', v['shifted']['verdict'], v['shifted']['brepcheck'], '| mapped', v['mapped_translation']['verdict'])
"
ls $W/diag/far6.done 2>/dev/null
echo ---probe; wc -l $W/diag/probe_seaport.jsonl; tail -3 $W/diag/probe_seaport.jsonl; grep -c '"sec"' $W/diag/probe_seaport.jsonl
python3 -c "
import json
rs=[json.loads(l) for l in open('$W/diag/probe_seaport.jsonl')]
big=sorted([r for r in rs if 'sec' in r and 'k' in r], key=lambda r:-r.get('d_rss',0))[:5]
for r in big: print(r)
slow=sorted([r for r in rs if 'sec' in r and 'k' in r], key=lambda r:-r['sec'])[:5]
for r in slow: print('slow', r)
"
