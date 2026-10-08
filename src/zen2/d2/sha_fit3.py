import sys, struct, collections, olefile, numpy as np, pymupdf
SRC='/work/in/src/'
o=olefile.OleFileIO(SRC+sys.argv[1]); d=pymupdf.open(SRC+sys.argv[2]); pg=d[0]; H=pg.rect.height
def recs(b):
    k=8; out=[]
    while k+6<=len(b):
        t,ln=struct.unpack_from('<HI',b,k); out.append((t,b[k+6:k+6+ln])); k+=6+ln
    return out
R=recs(o.openstream(sys.argv[3]).read())
S=np.array([struct.unpack_from('<4d',p,18) for t,p in R if t==24 and len(p)==50])
P=[]
for dr in pg.get_drawings():
    for it in dr['items']:
        if it[0]=='l': P.append((it[1].x*25.4/72e3,(H-it[1].y)*25.4/72e3,it[2].x*25.4/72e3,(H-it[2].y)*25.4/72e3))
P=np.array(P)
Pe=np.concatenate([P[:,:2],P[:,2:]]); Se=np.concatenate([S[:,:2],S[:,2:]])
for s in (1/250., 1/200., 1/100., 1/50., 1/500.):
    A=Se[::7][:1500]*s; Bp=Pe[::3][:4000]
    off=np.round((Bp[None,:,:]-A[:,None,:]).reshape(-1,2),4)
    c=collections.Counter(map(tuple,off)).most_common(2)
    t=np.array(c[0][0]); 
    pe=set(map(tuple,np.round(Pe,4))); m=sum((round(x,4),round(y,4)) in pe for x,y in Se*s+t)
    # tolerance matching
    from scipy.spatial import cKDTree
    kd=cKDTree(Pe); dist,_=kd.query(Se*s+t); 
    print('scale 1:%d'%round(1/s), 'offset', c, 'exact', m, 'of', len(Se), 'within 0.05mm', int((dist<5e-5).sum()), 'within 0.2mm', int((dist<2e-4).sum()))
