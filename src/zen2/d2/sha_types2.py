import sys, struct, collections, olefile, re
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
        u16=re.findall(rb'(?:[\x20-\x7e]\x00){2,}', p)
        dv=[]
        for off in range(18, len(p)-7):
            v=struct.unpack_from('<d',p,off)[0]
            if 1e-4<abs(v)<1e6 and off not in [x[0]+i for x in dv for i in range(1,8)]: dv.append((off,v))
        print(T,len(p),'hdr',hdr,'utf16',[s.decode('utf-16le')[:30] for s in u16][:4],'dbl', [(o_, '%.5g'%v) for o_,v in dv][:8])
        print('   hex@18', p[18:90].hex())
