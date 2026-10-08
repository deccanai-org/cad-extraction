import olefile, collections, sys
SRC='/work/in/src/'
rows=[l.rstrip('\n').split('\t') for l in open('/work/out/json/source_sha256.tsv')]
seen={}
for h,p in rows:
    if p.lower().endswith('.sha') and h not in seen: seen[h]=p
print('distinct sha', len(seen))
allstreams=collections.Counter(); bad=[]
for i,(h,p) in enumerate(seen.items()):
    try:
        o=olefile.OleFileIO(SRC+p)
    except Exception as e:
        bad.append((p,str(e)[:60])); continue
    for s in o.listdir(streams=True, storages=False):
        allstreams['/'.join(s)]+=1
    o.close()
print('bad', len(bad), bad[:3])
print(len(allstreams)); 
for k,v in allstreams.most_common(80): print(v, repr(k)[:90])
