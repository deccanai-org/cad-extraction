#!/bin/bash
cd /opt/pkgd4/logs || exit 0
/opt/conv/env/bin/python - <<'PY'
import json,glob,collections
miss=[]; final=collections.Counter(); notok=[]
for f in sorted(glob.glob('*.log')):
    t=open(f,errors='replace').read()
    i=t.rfind('\n{\n')
    try: d=json.loads(t[i+1:] if i>=0 else t[t.find('{'):])
    except Exception as e:
        notok.append((f,'unparsable',t[-600:])); continue
    st=d.get('status'); final[st]+=1
    if st!='ok': notok.append((f,st,t[-800:]))
    for x in ((d.get('apply') or {}).get('failed') or []):
        miss.append({'project_id':d.get('project_id'),'relpath':x.get('relpath'),'error':(x.get('error') or '')[:40]})
json.dump(miss,open('/opt/pkgd4/missing_files.json','w'),indent=0)
print('RESULT final',dict(final),'missing files',len(miss),'projects',len({m['project_id'] for m in miss}))
print('RESULT by error',collections.Counter(m['error'][:20] for m in miss))
print('RESULT by channel',collections.Counter(m['relpath'].split('/')[0]+'/'+m['relpath'].split('/')[1] for m in miss))
for f,st,tail in notok: print('RESULT NOTOK',f,st); print(tail)
PY
