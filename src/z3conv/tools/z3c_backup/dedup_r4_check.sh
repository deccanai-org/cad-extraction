#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
cd /opt/pkgdel_r4
/opt/conv/env/bin/python - <<'PY'
import sys, json, collections
sys.path.insert(0, '/opt/z3c/kit/coord')
import os; os.environ['PKG_ALLOW_WRITE']='0'
import pkgcore as pc, pkg
B=pc.BUCKET; ST=pc.PSTATE; BASE=f'{pc.DATASET}/{pc.ROUTE}/'
LOGK=f'{ST}/removals_done/2026-10-03.jsonl'
queue=[json.loads(l) for l in (pc.get_bytes(B,f'{ST}/removals_pending.jsonl') or b'').decode().splitlines() if l.strip()]
done={json.loads(l)['key'] for l in (pc.get_bytes(B,LOGK) or b'').decode().splitlines() if l.strip()}
pm=(pc.get_json(B,pkg.PRIMARY_KEY) or {}).get('map') or {}
proj={q['project_id'] for q in queue if q.get('reason')=='dedup_non_primary_project'}
rows=[q for q in queue if q.get('reason','').startswith('dedup_non_primary (') and q['project_id'] not in proj]
by=collections.defaultdict(list)
for q in rows:
    e=pm.get(q['model_key'])
    if not e or e.get('primary')==q['project_id']: continue
    by[q['project_id']].append(q)
mancache={}
def man(pid):
    if pid not in mancache: mancache[pid]=pc.read_manifest(B,f'{BASE}{pid}')
    return mancache[pid]
tot=0; bad=0
for pid,qs in sorted(by.items()):
    m=man(pid); mids={q['model_key'].rsplit(':',1)[-1]:q for q in qs}
    drop=[r for r in m if r.get('modality')=='step' and r.get('model_id') in mids and r.get('step_source') in('ifc','db1','sds2') and f"{BASE}{pid}/{r['relpath']}" not in done]
    if not drop: continue
    ok=0; miss=[]
    for r in drop:
        prim=pm[mids[r['model_id']]['model_key']]['primary']
        pmn=man(prim)
        if any(x.get('model_id')==r['model_id'] and x.get('modality')=='step' for x in pmn) or any(r['model_id'] in [a.get('model_id') for a in (x.get('also_models') or [])] for x in pmn): ok+=1
        else: miss.append((prim[:70], r['relpath']))
    tot+=len(drop); bad+=len(miss)
    print(f"RESULT drop {len(drop)} kept-in-primary {ok} MISSING {len(miss)} | {pid[:110]}")
    for x in miss[:3]: print('   missing in primary:', x)
print(f"RESULT TOTAL drop {tot} missing_in_primary {bad}")
PY
