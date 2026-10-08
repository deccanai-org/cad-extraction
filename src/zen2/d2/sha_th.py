import sys, struct, collections, olefile, re, math, pymupdf
sys.path.insert(0,'/work/2d')
import sha2dxf as S
SRC='/work/in/src/'
dec=S.Decoder(SRC+sys.argv[1])
pg=pymupdf.open(SRC+sys.argv[2])[0]; Hp=pg.rect.height; K=25.4/72e3
spans=collections.defaultdict(list)
for b in pg.get_text('dict')['blocks']:
    for l in b.get('lines',[]):
        for sp in l['spans']: spans[sp['text'].strip()].append((sp['origin'][0]*K,(Hp-sp['origin'][1])*K,sp['size']*K, sp['font'], sp['bbox']))
rows=[]
for storage in ['', 'JSite4756']:
    for n in dec.sheet_streams(storage):
        for t,p in S.recs(dec.o.openstream(n).read()):
            if t&0x7fff!=77: continue
            r=S.find_str(p)
            if not r: continue
            k,L,s=r; q=S.find_pos(p,k+2+2*L)
            if not q: continue
            x,y,c,sn=q[1]
            cand=[v for v in spans.get(s.strip(),[]) if math.hypot(v[0]-x,v[1]-y)<0.02]
            if not cand: continue
            size=cand[0][2]
            dbl=[]
            for off in range(18,len(p)-7):
                if k<=off<k+2+2*L: continue
                v=struct.unpack_from('<d',p,off)[0]
                if 1e-4<v<0.05: dbl.append((off-(k+2+2*L), round(v/size,4)))
            rows.append((s[:14], round(size*1000,2), cand[0][3], 'pre', p[18:k].hex()[:40], dbl[:8]))
for r in rows[:30]: print(r)
