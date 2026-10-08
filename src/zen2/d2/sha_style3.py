import sys, struct, collections, olefile, re
SRC='/work/in/src/'
o=olefile.OleFileIO(SRC+sys.argv[1]); st=sys.argv[2]; T=int(sys.argv[3]); N=int(sys.argv[4])
def recs(b):
    k=8; out=[]
    while k+6<=len(b):
        t,ln=struct.unpack_from('<HI',b,k); out.append((t,b[k+6:k+6+ln])); k+=6+ln
    return out
R=recs(o.openstream(st+'/Sheet6' if st else 'Sheet6').read())
S={}
for t,p in recs(o.openstream((st+'/' if st else '')+'StyleCluster').read()):
    if len(p)>=16: S[struct.unpack_from('<H',p,14)[0]]=(t,p)
S0={struct.unpack_from('<I',p,0)[0]:struct.unpack_from('<H',p,14)[0] for t,p in recs(o.openstream((st+'/' if st else '')+'StyleCluster').read()) if len(p)>=16}
def show(i, depth=0):
    if i not in S or depth>2: print('  '*depth,'style',i,'missing'); return
    t,p=S[i]
    u16=[s.decode('utf-16le') for s in re.findall(rb'(?:[\x20-\x7e]\x00){3,}', p)]
    refs=[S0[v] for v in struct.unpack_from('<%dI'%((len(p)-16)//4),p,16) if v in S0 and S0[v]!=i] if len(p)>20 else []
    dbl=[(k,'%.5g'%struct.unpack_from('<d',p,k)[0]) for k in range(16,len(p)-7) if 1e-6<abs(struct.unpack_from('<d',p,k)[0])<1e5]
    print('  '*depth,'style',hex(i),'type',t,'len',len(p),u16[:2],'refs',[hex(r) for r in refs[:5]],'dbl',dbl[:6], p[12:40].hex())
    for r in refs[:3]: show(r, depth+1)
seen=set(); n=0
for t,p in R:
    if t&0x7fff!=T: continue
    sid=struct.unpack_from('<I',p,14)[0]
    if sid in seen: continue
    seen.add(sid); n+=1
    if n>N: break
    print('rec type',t,'len',len(p),'layer',struct.unpack_from('<I',p,8)[0],'style',sid)
    show(sid)
