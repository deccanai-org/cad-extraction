import sys, struct, collections, olefile, json
SRC='/work/in/src/'
rows=[l.rstrip('\n').split('\t') for l in open('/work/out/json/source_sha256.tsv')]
seen={}
for h,p in rows:
    if p.lower().endswith('.sha') and h not in seen: seen[h]=p
cnt=collections.Counter(); files=collections.Counter(); lens=collections.defaultdict(collections.Counter)
strm=collections.Counter()
for h,p in seen.items():
    o=olefile.OleFileIO(SRC+p)
    ft=set()
    for s in o.listdir(streams=True, storages=False):
        if not s[-1].startswith('Sheet'): continue
        b=o.openstream('/'.join(s)).read()
        if len(b)<=8: continue
        strm['/'.join(x if not x.startswith('JSite') else 'JSite*' for x in s)]+=1
        k=8
        while k+6<=len(b):
            t,ln=struct.unpack_from('<HI',b,k); cnt[t]+=1; lens[t][ln]+=1; ft.add(t); k+=6+ln
    for t in ft: files[t]+=1
    o.close()
print('streams', strm.most_common(10))
for t,c in cnt.most_common(45):
    print(t, c, 'files', files[t], 'lens', dict(lens[t].most_common(5)))
