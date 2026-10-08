import sys, struct, collections, olefile, numpy as np
SRC='/work/in/src/'
o=olefile.OleFileIO(SRC+sys.argv[1])
def recs(b):
    k=8; out=[]
    while k+6<=len(b):
        t,ln=struct.unpack_from('<HI',b,k); out.append((t,b[k+6:k+6+ln])); k+=6+ln
    return out
R=recs(o.openstream(sys.argv[2]).read())
for T in [int(x) for x in sys.argv[3].split(',')]:
    ex=[p for t,p in R if t==T][:2]
    for p in ex:
        hdr=struct.unpack_from('<IIIHI',p,0)
        rest=p[18:]
        dv=[struct.unpack_from('<d',rest,i)[0] for i in range(0,len(rest)-7,8)]
        print(T,len(p),'hdr',hdr,'| f8@18:',' '.join('%.5g'%v if abs(v)<1e7 and (abs(v)>1e-6 or v==0) else '~' for v in dv)[:300])
        print('   hex@18', rest[:80].hex())
