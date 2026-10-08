import olefile, sys
SRC='/work/in/src/'
rows=[l.rstrip('\n').split('\t') for l in open('/work/out/json/source_sha256.tsv')]
p=[p for h,p in rows if p.lower().endswith('.sha')][0]
print(p)
o=olefile.OleFileIO(SRC+p)
for s in o.listdir(streams=True, storages=False):
    n='/'.join(s); sz=o.get_size(n)
    if n.startswith('JSite'): continue
    d=o.openstream(n).read()
    print(repr(n)[:40], sz, d[:16].hex())
for n in ['TaggedTxtData/TitleBlockInfo','TaggedTxtData/General','TaggedTxtData/TitleArea','TaggedTxtData/Revision']:
    d=o.openstream(n).read(); print('==',n, len(d)); print(repr(d[:300]))
m=o.get_metadata(); print({k:getattr(m,k) for k in ['title','subject','author','last_saved_by','create_time','last_saved_time','creating_application','num_pages','company'] })
