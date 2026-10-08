import sys, struct, collections, olefile, re
SRC='/work/in/src/'
o=olefile.OleFileIO(SRC+sys.argv[1])
def recs(b):
    k=8; out=[]
    while k+6<=len(b):
        t,ln=struct.unpack_from('<HI',b,k); out.append((t,b[k+6:k+6+ln])); k+=6+ln
    return out
R=recs(o.openstream(sys.argv[2]).read())
n=0
for t,p in R:
    if t&0x7fff!=77: continue
    n+=1
    if n>int(sys.argv[3]): break
    h=struct.unpack_from('<IIIHI',p,0)
    a=struct.unpack_from('<HHHHIH',p,18)
    sl=a[5]; s=p[30:30+2*sl].decode('utf-16le','replace'); e=30+2*sl
    tail=p[e:]
    ds=[struct.unpack_from('<d',tail,i)[0] for i in range(0,len(tail)-7)]
    good=[(i,round(v,5)) for i,v in enumerate(ds) if 1e-5<abs(v)<1e4]
    print(len(p),h[2],a[:5],repr(s[:40]),'tail',len(tail),tail[:12].hex(), good[:10])
