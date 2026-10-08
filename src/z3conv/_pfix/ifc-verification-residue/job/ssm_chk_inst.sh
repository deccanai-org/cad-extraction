#!/bin/bash
W=/work/agentwork/ifc-verification-residue
S=$W/w/mnc_dev3/4f6b8e2e96937507/out.step
ls -la $S
/opt/conv/env/bin/python - <<'PY'
import re
S='/work/agentwork/ifc-verification-residue/w/mnc_dev3/4f6b8e2e96937507/out.step'
ents={}
for line in open(S):
    m=re.match(r'#(\d+)=([A-Z_0-9]+)\((.*)\);',line.strip())
    if m: ents[int(m.group(1))]=(m.group(2),m.group(3))
mi=[(k,v) for k,v in ents.items() if v[0]=='MAPPED_ITEM']
print('mapped items', len(mi))
for k,(t,b) in mi[:6]:
    refs=[int(x) for x in re.findall(r'#(\d+)',b)]
    ax=ents[refs[1]]
    r2=[int(x) for x in re.findall(r'#(\d+)',ax[1])]
    print(k, 'placement', ax, '-> point', ents[r2[0]], 'dirs', ents[r2[1]], ents[r2[2]])
# max decimals of ordinary points vs placement points
import collections
pl=set()
for k,(t,b) in mi:
    refs=[int(x) for x in re.findall(r'#(\d+)',b)]
    r2=[int(x) for x in re.findall(r'#(\d+)',ents[refs[1]][1])]
    pl.add(r2[0])
dec=collections.Counter()
for k in pl:
    for v in re.findall(r'[-0-9.E]+', ents[k][1].split('(',1)[1]):
        if '.' in v: dec[len(v.split('.')[1].split('E')[0])]+=1
print('decimals in placement points', dict(dec))
PY
