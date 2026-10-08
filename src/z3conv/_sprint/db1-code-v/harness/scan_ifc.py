import gzip, json, os, glob, posixpath
out = []
for f in sorted(glob.glob('/opt/db1v/man/*.jsonl.gz')):
    E = []
    try:
        for l in gzip.open(f):
            try: E.append(json.loads(l))
            except Exception: pass
    except Exception: continue
    db1 = [e for e in E if e.get('path', '').lower().endswith('.db1')]
    ifc = [e for e in E if e.get('path', '').lower().endswith('.ifc')]
    if not db1 or not ifc: continue
    for d in db1:
        mdir = posixpath.dirname(d['path'])
        if not mdir: continue
        c = [dict(path=e['path'], key=e.get('key'), size=e.get('size'), sha=e.get('sha256')) for e in ifc if e['path'].startswith(mdir + '/')]
        if c: out.append(dict(man=os.path.basename(f), sha=d.get('sha256'), key=d.get('key'), path=d['path'], size=d.get('size'), ifcs=c[:20]))
json.dump(out, open('/opt/db1v/ifc_cands.json', 'w')); print(len(out))
