#!/bin/bash
cd /work/agentwork/cut-not-applied; python3 - <<'P'
import json, gzip
for v in ('pipes3/nofit', 'pipes3/fit', 'pipes5/kitn', 'pipes5/kitnp7'):
    d = v + '/0762effe61de88c0'
    pl = {p[0]: p for p in json.load(gzip.open(d + '/convert.json.parts.json.gz', 'rt'))}
    st = {}
    for l in gzip.open(d + '/step_parts.jsonl.gz', 'rt'):
        s = json.loads(l); st[s['pid']] = s
    for pid in (52418, 65130):
        p = pl.get(pid); s = st.get(p[5]) if p else None
        print(v, pid, p[1] if p else None, 'n_cuts', p[6] if p else None, 'faces', s and s.get('faces'), 'vol', s and s.get('volume'), 'bbox', s and s.get('bbox'))
P
