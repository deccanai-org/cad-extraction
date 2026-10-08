import sys, struct, collections, olefile, re
SRC='/work/in/src/'
o=olefile.OleFileIO(SRC+sys.argv[1])
def recs(b):
    k=8; out=[]
    while k+6<=len(b):
        t,ln=struct.unpack_from('<HI',b,k); out.append((t,b[k+6:k+6+ln])); k+=6+ln
    return out
ids=set(int(x) for x in sys.argv[3].split(','))
for n in sys.argv[2].split(','):
    R=recs(o.openstream(n).read())
    byid={struct.unpack_from('<I',p,0)[0]:(t,p) for t,p in R if len(p)>=4}
    for i in sorted(ids):
        if i in byid:
            t,p=byid[i]
            u16=[s.decode('utf-16le') for s in re.findall(rb'(?:[\x20-\x7e]\x00){3,}', p)]
            print(n, 'id',i,'type',t,'len',len(p),'hdr',struct.unpack_from('<IIIHI',p,0) if len(p)>=18 else '', u16[:3])
            print('   ', p[18:80].hex(), ['%.4g'%struct.unpack_from('<d',p,k)[0] for k in range(18,min(len(p)-7,90),8)])
