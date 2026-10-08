import pymupdf, sys, collections, json
SRC='/work/in/src/'
rows=[l.rstrip('\n').split('\t') for l in open('/work/out/json/source_sha256.tsv')]
seen={}; 
for h,p in rows:
    if p.lower().endswith('.pdf') and h not in seen: seen[h]=p
prod=collections.Counter(); sizes=collections.Counter(); rot=collections.Counter(); npages=collections.Counter()
bad=[]
for h,p in seen.items():
    try:
        d=pymupdf.open(SRC+p)
    except Exception as e:
        bad.append((p,str(e))); continue
    m=d.metadata or {}
    prod[(m.get('producer','') or '')[:40]+' | '+(m.get('creator','') or '')[:40]]+=1
    npages[d.page_count]+=1
    for pg in d:
        r=pg.rect; sizes[(round(pg.mediabox.width*25.4/72), round(pg.mediabox.height*25.4/72))]+=1; rot[pg.rotation]+=1
print('distinct',len(seen),'bad',len(bad), bad[:3])
print('producers',prod.most_common(15))
print('npages',sorted(npages.items()))
print('sizes mm (mediabox w,h)',sizes.most_common(12))
print('rotation',rot)
