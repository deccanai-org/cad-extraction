import sys, struct, collections, olefile, numpy as np, pymupdf
SRC='/work/in/src/'
o=olefile.OleFileIO(SRC+sys.argv[1]); d=pymupdf.open(SRC+sys.argv[2]); pg=d[0]; H=pg.rect.height
def recs(b):
    k=8; out=[]
    while k+6<=len(b):
        t,ln=struct.unpack_from('<HI',b,k); out.append((t,b[k+6:k+6+ln])); k+=6+ln
    return out
R=recs(o.openstream(sys.argv[3]).read())
for L in (50,66):
    ps=[p for t,p in R if t==24 and len(p)==L]
    hdr=collections.Counter(p[4:18].hex() for p in ps).most_common(3)
    a=np.array([struct.unpack_from('<4d',p,L-32) for p in ps])
    ln=np.hypot(a[:,2]-a[:,0],a[:,3]-a[:,1])
    print(L,len(ps),hdr, 'x',np.percentile(a[:,0],[0,5,50,95,100]).round(3),'y',np.percentile(a[:,1],[0,5,50,95,100]).round(3),'len',np.percentile(ln,[5,50,95]).round(4))
    if L==66: print(' extra', collections.Counter(p[18:34].hex() for p in ps).most_common(3))
