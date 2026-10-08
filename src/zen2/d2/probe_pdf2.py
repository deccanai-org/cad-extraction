import pymupdf, sys, collections, os, time
SRC='/work/in/src/'
rows=[l.rstrip('\n').split('\t') for l in open('/work/out/json/source_sha256.tsv')]
seen={}
for h,p in rows:
    if p.lower().endswith('.pdf') and h not in seen: seen[h]=p
f='07-04-2026(Comments updated)/P16093-16-01-21-1731.PDF'
print('bad file size', os.path.getsize(SRC+f)); print(open(SRC+f,'rb').read(64))
bycat=collections.defaultdict(list)
for h,p in seen.items():
    try: d=pymupdf.open(SRC+p)
    except: continue
    pr=(d.metadata.get('producer') or '')[:6]
    bycat[pr].append(p)
for k,v in bycat.items():
    for p in v[:2]:
        d=pymupdf.open(SRC+p); pg=d[0]
        t=time.time(); dr=pg.get_drawings(extended=True); t1=time.time()-t
        types=collections.Counter(x.get('type') for x in dr)
        items=collections.Counter(it[0] for x in dr if 'items' in x for it in x['items'])
        cols=collections.Counter((x.get('color'), x.get('width')) for x in dr if x.get('type') in ('s','fs'))
        fills=collections.Counter(x.get('fill') for x in dr if x.get('type') in ('f','fs'))
        dash=collections.Counter(x.get('dashes') for x in dr if x.get('type') in ('s','fs'))
        td=pg.get_text('dict'); spans=[s for b in td['blocks'] if b['type']==0 for l in b['lines'] for s in l['spans']]
        imgs=pg.get_images(full=True)
        fonts=pg.get_fonts()
        print('====',k, p[-60:], 'size', os.path.getsize(SRC+p))
        print(' drawings',len(dr),'%.1fs'%t1, types, items)
        print(' stroke col/width', cols.most_common(6)); print(' fills', fills.most_common(4)); print(' dashes', dash.most_common(4))
        print(' spans',len(spans), 'lines dirs', collections.Counter(tuple(round(c,2) for c in l['dir']) for b in td['blocks'] if b['type']==0 for l in b['lines']).most_common(3))
        print(' sample spans', [(s['text'][:20], round(s['size'],2), s['font']) for s in spans[:4]])
        print(' imgs', [(i[2],i[3],i[5]) for i in imgs][:4], 'fonts', [(f[3],f[1]) for f in fonts][:6])
