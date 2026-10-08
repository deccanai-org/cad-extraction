import sys, struct, collections, olefile, re, math, pymupdf
sys.path.insert(0,'/work/2d')
from sha_text3 import recs, find_str, find_pos
SRC='/work/in/src/'
o=olefile.OleFileIO(SRC+sys.argv[1])
pg=pymupdf.open(SRC+sys.argv[2])[0]; H=pg.rect.height; k2=25.4/72e3
spans={}
for b in pg.get_text('dict')['blocks']:
    for l in b.get('lines',[]):
        for sp in l['spans']:
            bb=sp['bbox']
            spans.setdefault(sp['text'].strip(),[]).append((bb[0]*k2,(H-bb[3])*k2,bb[2]*k2,(H-bb[1])*k2, sp['size']*k2, l['dir']))
tab=collections.defaultdict(collections.Counter)
for n in sys.argv[3].split(','):
    for t,p in recs(o.openstream(n).read()):
        if t&0x7fff!=77: continue
        r=find_str(p)
        if not r: continue
        k,L,s=r; q=find_pos(p,k+2+2*L)
        if not q: continue
        x,y,c,sn=q[1]; j=p[q[0]+32:q[0]+36].hex()
        if s.strip() not in spans or abs(sn)>0.01: continue
        x0,y0,x1,y1,sz,d=min(spans[s.strip()], key=lambda v: math.hypot((v[0]+v[2])/2-x,(v[1]+v[3])/2-y))
        if math.hypot((x0+x1)/2-x,(y0+y1)/2-y)>0.03: continue
        tol=0.3*sz
        hx='L' if abs(x-x0)<tol else 'C' if abs(x-(x0+x1)/2)<tol else 'R' if abs(x-x1)<tol else '?'
        vy='T' if abs(y-y1)<tol else 'M' if abs(y-(y0+y1)/2)<tol else 'B' if abs(y-y0)<tol else '?'
        tab[j][hx+vy]+=1
for j,c in tab.items(): print(j, dict(c))
