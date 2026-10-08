#!/bin/bash
cd /opt/pkgd4/logs 2>/dev/null || exit 0
/opt/conv/env/bin/python - <<'PY'
import json,glob,re,collections
c=collections.Counter(); ex=[]
for f in glob.glob('*.log'):
    t=open(f,errors='replace').read()
    if '"status": "partial"' not in t: continue
    i=t.rfind('\n{'); 
    try: d=json.loads(t[t.find('{', t.rfind('"status": "partial"')-4000 if False else 0):])
    except Exception: d=None
    m=re.findall(r'"failed": \[(.*?)\]', t, re.S)
    n=sum(x.count('"key"')+x.count('NoSuchKey') for x in m)
    c['projects']+=1
    if len(ex)<3: ex.append((f, t[-1500:]))
print('RESULT partial projects', c['projects'])
for f,tail in ex[:2]: print('RESULT ==',f); print(tail)
PY
