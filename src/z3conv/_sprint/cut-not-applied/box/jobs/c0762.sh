#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/*.py tools/
for v in nofit fit; do python3 -c "
import json; c=json.load(open('pipes3/$v/0762effe61de88c0/convert.json')); k=json.load(open('pipes3/$v/0762effe61de88c0/check.json'))
print('$v', 'written', c.get('written'), 'cuts_applied', c.get('cuts_applied'), 'fittings', c.get('fittings'), 'cut_stats', c.get('cut_stats'))
print('   check', {x: k.get(x) for x in ('roots','solids','invalid','nonpos','empty_roots','status','volume_total') if x in k}, list(k.keys())[:30])"; done
PIPE_A=pipes3/nofit PIPE_B=pipes3/fit /opt/conv/env/bin/python tools/pipe_cmp.py 0762effe61de88c0 2>&1 | python3 -c "
import sys, json
for l in sys.stdin:
    if not l.startswith('{'): print(l[:400]); continue
    r = json.loads(l); rep = r.pop('report', {}) or {}; t = rep.pop('table', None)
    print({k: r[k] for k in r if k not in ('grew_examples',)})
    print('report', rep)
    for row in (t or []): print('   ', row)
"
