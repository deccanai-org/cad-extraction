#!/bin/bash
cd /work/agentwork/cut-not-applied
python3 - <<'P'
import json, gzip, glob, re, collections, os
tot = collections.Counter(); per = []
for f in glob.glob('convall/kitp3/*/convert.json.parts.json.gz'):
    i = f.split('/')[2]
    c = collections.Counter()
    for pid, prof, cat, st, how, gid, nc in json.load(gzip.open(f, 'rt')):
        if prof and re.fullmatch(r'\d+(\.\d+)?', prof.strip()):
            c[(st, how)] += 1
    if c:
        per.append((i, dict(c))); tot.update(c)
for p in sorted(per, key=lambda x: -sum(x[1].values())): print(p)
print('TOTAL', dict(tot))
P
