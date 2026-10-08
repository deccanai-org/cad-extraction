import sys, struct, numpy as np, olefile, pymupdf, collections
SRC='/work/in/src/'
o=olefile.OleFileIO(SRC+sys.argv[1]); d=pymupdf.open(SRC+sys.argv[2]); pg=d[0]; H=pg.rect.height
ref=set()
for dr in pg.get_drawings():
    for it in dr['items']:
        if it[0]=='l':
            for p in it[1:3]: ref.add((round(p.x*25.4/72/1000,4), round((H-p.y)*25.4/72/1000,4)))
b=o.openstream(sys.argv[3]).read()
print(len(b), b[:48].hex())
hits=[]
for k in range(len(b)-16):
    x,y=struct.unpack_from('<2d',b,k)
    if 0<x<1.2 and 0<y<1.2 and (round(x,4),round(y,4)) in ref: hits.append(k)
print('hits',len(hits), hits[:30])
gaps=collections.Counter(np.diff(hits)); print('gaps', gaps.most_common(10))
for k in hits[:3]:
    s=max(0,k-80); print(k, b[s:k].hex(), '|', b[k:k+48].hex())
