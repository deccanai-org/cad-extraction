import sys, struct, olefile
SRC='/work/in/src/'
o=olefile.OleFileIO(SRC+sys.argv[1])
def recs(b):
    k=8; out=[]
    while k+6<=len(b):
        t,ln=struct.unpack_from('<HI',b,k); out.append((t,b[k+6:k+6+ln])); k+=6+ln
    return out
stor=set('/'.join(s) for s in o.listdir(streams=False, storages=True))
for s in o.listdir(streams=True, storages=False):
    if not s[-1].startswith('Sheet'): continue
    n='/'.join(s); b=o.openstream(n).read()
    if len(b)<=8: continue
    base='/'.join(s[:-1])
    for t,p in recs(b):
        if t&0x7fff!=61: continue
        found=None
        for off in range(18,len(p)-4):
            v=struct.unpack_from('<I',p,off)[0]
            cand=(base+'/' if base else '')+'JSite%d'%v
            if 100<v<100000 and cand in stor: found=(off,v,cand); break
        if found:
            off=found[0]; m=struct.unpack_from('<7d',p,off+8)
            print(n, t, len(p), 'jsite@',off, found[2], 'M', ['%.6g'%x for x in m], 'hdr', struct.unpack_from('<IIIHI',p,0))
        else:
            print(n, t, len(p), 'no jsite ref')
