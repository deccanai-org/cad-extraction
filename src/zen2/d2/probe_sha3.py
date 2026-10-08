import olefile, sys, re, collections
import xml.etree.ElementTree as ET
SRC='/work/in/src/'
rows=[l.rstrip('\n').split('\t') for l in open('/work/out/json/source_sha256.tsv')]
p=[p for h,p in rows if p.lower().endswith('.sha')][0]
o=olefile.OleFileIO(SRC+p)
tot=collections.Counter()
for s in o.listdir(streams=True, storages=False):
    n='/'.join(s); tot[s[0] if s[0].startswith('JSite') else 'root']+=o.get_size(n)
print(tot.most_common(12))
for n in o.listdir(streams=True, storages=False):
    n='/'.join(n)
    if n.startswith('TaggedTxtData/'):
        d=o.openstream(n).read().decode('utf-8','replace')
        try:
            r=ET.fromstring(d.strip())
            vals=[(e.tag, (e.text or '').strip()[:30]) for e in r.iter() if (e.text or '').strip()]
            print(n, vals[:14])
        except Exception as e: print(n,'XMLERR',e, d[:80])
print(o.openstream('JTaggedTxtStgList').read().decode('utf-16le','replace')[:80])
js=[s for s in o.listdir(streams=True,storages=False) if s[0].startswith('JSite')]
c=collections.Counter(s[0] for s in js); print(c)
first=js[0][0]
for s in js:
    if s[0]==first: print('/'.join(s), o.get_size('/'.join(s)))
