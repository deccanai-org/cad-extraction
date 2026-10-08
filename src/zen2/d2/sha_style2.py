import sys, struct, collections, olefile, re
SRC='/work/in/src/'
o=olefile.OleFileIO(SRC+sys.argv[1])
def recs(b):
    k=8; out=[]
    while k+6<=len(b):
        t,ln=struct.unpack_from('<HI',b,k); out.append((t,b[k+6:k+6+ln])); k+=6+ln
    return out
R=recs(o.openstream(sys.argv[2]).read())
c=collections.Counter()
for t,p in R:
    c[t]+=1
    if c[t]>int(sys.argv[3]): continue
    u16=[s.decode('utf-16le') for s in re.findall(rb'(?:[\x20-\x7e]\x00){3,}', p)]
    ints=struct.unpack_from('<%dI'%min(8,len(p)//4),p,0)
    print(t,len(p),ints[:6],u16[:2], p[:40].hex())
