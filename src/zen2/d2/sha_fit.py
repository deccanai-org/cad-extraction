import sys, struct, collections, olefile, numpy as np, pymupdf
SRC='/work/in/src/'
o=olefile.OleFileIO(SRC+sys.argv[1]); d=pymupdf.open(SRC+sys.argv[2]); pg=d[0]; H=pg.rect.height
def recs(b):
    k=8; out=[]
    while k+6<=len(b):
        t,ln=struct.unpack_from('<HI',b,k); out.append((t,b[k+6:k+6+ln])); k+=6+ln
    return out
R=recs(o.openstream(sys.argv[3]).read())
segs=np.array([struct.unpack_from('<4d',p,18) for t,p in R if t==24])
print('segs',len(segs),'x',segs[:,[0,2]].min(),segs[:,[0,2]].max(),'y',segs[:,[1,3]].min(),segs[:,[1,3]].max())
P=[]
for dr in pg.get_drawings():
    for it in dr['items']:
        if it[0]=='l': P.append((it[1].x*25.4/72e3,(H-it[1].y)*25.4/72e3,it[2].x*25.4/72e3,(H-it[2].y)*25.4/72e3))
P=np.array(P); print('pdf segs',len(P))
# length-ratio histogram for axis-aligned segments
def lens(a): return np.hypot(a[:,2]-a[:,0],a[:,3]-a[:,1])
Ls=lens(segs); Lp=lens(P)
Ls=Ls[Ls>0]; Lp=Lp[Lp>1e-4]
r=(Lp[None,:2000]/Ls[:2000,None]).ravel(); r=r[(r>1e-5)&(r<10)]
h,e=np.histogram(np.log10(r),bins=4000)
top=np.argsort(h)[-5:][::-1]; print('scale candidates', [(round(10**((e[i]+e[i+1])/2),6),h[i]) for i in top])
# for best scale, find offset by voting on endpoints
pe=set((round(x,4),round(y,4)) for x,y in np.concatenate([P[:,:2],P[:,2:]]))
for s in [10**((e[i]+e[i+1])/2) for i in top[:3]]:
    # vote offsets: pdf_pt - s*sha_pt for sample
    A=np.concatenate([segs[:,:2],segs[:,2:]])[:3000]*s; B=np.concatenate([P[:,:2],P[:,2:]])[:6000]
    off=(B[None,:,:]-A[:,None,:]).reshape(-1,2); off=np.round(off,3)
    c=collections.Counter(map(tuple,off)).most_common(3); print('s',s,'offsets',c)
