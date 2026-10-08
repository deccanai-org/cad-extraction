import gzip, json, os, glob, collections, posixpath
out = []; kc = collections.Counter()
for f in sorted(glob.glob('/opt/db1v/man/*.jsonl.gz')):
    E = []
    try:
        for l in gzip.open(f):
            try: E.append(json.loads(l))
            except Exception: pass
    except Exception as e:
        continue
    db1 = [e for e in E if e.get('path', '').lower().endswith('.db1')]
    nc = [e for e in E if e.get('path', '').lower().endswith(('.nc1', '.nc'))]
    if not db1 or not nc: continue
    for e in nc: kc[(e.get('key') or '')[:7]] += 1
    for d in db1:
        mdir = posixpath.dirname(d['path'])
        ncs = [e for e in nc if e['path'].startswith(mdir + '/')] if mdir else nc
        if not ncs: continue
        dirs = collections.Counter(posixpath.dirname(e['path']) for e in ncs)
        out.append(dict(man=os.path.basename(f), sha=d.get('sha256'), key=d.get('key'), path=d['path'], size=d.get('size'), n_nc=len(ncs),
                        nc_dirs=dirs.most_common(), nc_keys_sample=[e.get('key') for e in ncs[:2]], nc_dedup=sum(1 for e in ncs if (e.get('key') or '').startswith('disk12'))))
json.dump(out, open('/opt/db1v/nc_cands.json', 'w'))
print(len(out), kc.most_common())
print(json.dumps(out[:2])[:1500])
