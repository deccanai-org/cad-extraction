import sys, struct, collections, olefile, re
SRC='/work/in/src/'
o=olefile.OleFileIO(SRC+sys.argv[1])
def recs(b):
    k=8; out=[]
    while k+6<=len(b):
        t,ln=struct.unpack_from('<HI',b,k); out.append((t,b[k+6:k+6+ln])); k+=6+ln
    return out
def find_str(p):
    for k in range(18, len(p)-3):
        L=struct.unpack_from('<H',p,k)[0]
        if 1<=L<=2000 and k+2+2*L<=len(p):
            try: s=p[k+2:k+2+2*L].decode('utf-16le')
            except: continue
            if all(32<=ord(c)<0x2500 or c in '\r\n\t' for c in s) and sum(c.isalnum() for c in s)>=1:
                return k,L,s
    return None
R=recs(o.openstream(sys.argv[2]).read())
pat=collections.Counter(); n=0
for t,p in R:
    if t&0x7fff!=77: continue
    r=find_str(p)
    if not r: print('nostr',len(p)); continue
    k,L,s=r; e=k+2+2*L; tail=p[e:]
    pre=p[18:k].hex()
    pat[(k-18,len(tail))]+=1
    n+=1
    if n<=int(sys.argv[3]):
        # doubles in tail at offset 2
        dv=[struct.unpack_from('<d',tail,i)[0] for i in range(2,len(tail)-7,8)]
        print(len(p),'pre',pre,'str@',k,repr(s[:30]),'tail',len(tail),tail[:2].hex(),['%.5g'%v for v in dv][:6], tail[-6:].hex())
print(pat.most_common(10))
