#!/bin/bash
cd /work/agentwork/audit-sds2-v5x
/opt/conv/env/bin/python - <<'PY'
import json, glob, collections, re, os
def lab(c):
    m = re.match(r'z3-sds2-(v[\d.]+?)-2026', str(c or '')); return m.group(1) if m else None
c = collections.Counter(); ex = {}
for jj in glob.glob('s3/out/*/job.json') + glob.glob('s3/out/*/*/job.json') + glob.glob('s3/out/_not_accepted/*/job.json') + glob.glob('s3/out/_not_accepted/*/*/job.json'):
    j = json.load(open(jj)); na = '_not_accepted' in jj
    k = (na, lab(j.get('code')), repr(j.get('published')), tuple(sorted(x for x in j if x not in ('id','name','version','paths','qa','qa_reasons','stage2','validate','inventory','code','converter','converted','published'))))
    c[k] += 1; ex.setdefault(k, jj)
for k, v in c.most_common(): print(v, k, ex[k])
print(sorted(set(os.path.basename(f).split('_')[-1] for f in glob.glob('s3/out/**/*', recursive=True) if os.path.isfile(f))))
R = {os.path.basename(f)[:-5]: json.load(open(f)) for f in glob.glob('s3/sds2/results/*.json')}
s1 = [r for r in R.values() if r.get('status') == 'ok_stage1']
r = s1[0]; print(json.dumps({k: r[k] for k in r if k not in ('log_tail','paths_sample','fetch','inventory','stage2')}, default=str)[:3000])
print()
fails = collections.Counter((lab(r.get('code')), r.get('reason')) for r in R.values() if r.get('status') == 'fail'); print(fails.most_common())
s1r = collections.Counter((lab(r.get('code')), r.get('stage2_reason')) for r in R.values() if r.get('status') == 'ok_stage1'); print(s1r)
nolab = [r for r in R.values() if not r.get('converter')]
for r in nolab: print(r['id'], r.get('code'), r.get('status'), r.get('reason'), r.get('error'), str(r.get('trace'))[-300:])
print(open('s3/ctl/sds2_converter.json').read())
print(sorted(os.listdir('s3/sds2/logs'))[:3], len(os.listdir('s3/sds2/logs')))
f = sorted(glob.glob('s3/sds2/logs/*.log'), key=os.path.getsize)[-1]; t = open(f).read().splitlines(); print(f, len(t)); print('\n'.join(t[:5])); print('\n'.join(t[-8:]))
print(len(os.listdir('s3/sds2/deferred')), len(os.listdir('s3/sds2/claims')), len(os.listdir('s3/sds2/retry')) if os.path.isdir('s3/sds2/retry') else None)
d = [json.load(open(f)) for f in glob.glob('s3/sds2/deferred/*.json')]; print(collections.Counter(x.get('kills') for x in d)); print(d[0])
cl = [json.load(open(f)) for f in glob.glob('s3/sds2/claims/*.json')]; print(collections.Counter(lab(x.get('code')) for x in cl))
PY
