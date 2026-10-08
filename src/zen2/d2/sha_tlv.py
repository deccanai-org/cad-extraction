import sys, struct, collections, olefile
SRC='/work/in/src/'
o=olefile.OleFileIO(SRC+sys.argv[1])
def walk(b, start):
    k=start; recs=[]
    while k+6<=len(b):
        t,ln=struct.unpack_from('<HI',b,k)
        if ln>len(b)-k-6: return recs, k
        recs.append((k,t,ln)); k+=6+ln
    return recs,k
for s in o.listdir(streams=True, storages=False):
    n='/'.join(s); b=o.openstream(n).read()
    if not b.startswith(bytes.fromhex('44f5906c')) or len(b)<200: continue
    best=None
    for st in range(8,64):
        recs,end=walk(b,st)
        if best is None or (end,len(recs))>(best[1],len(best[0])): best=(recs,end,st)
    recs,end,st=best
    ty=collections.Counter(t for _,t,_ in recs)
    print(n[:40], len(b), 'hdr', b[4:st].hex()[:40], 'start',st,'end',end,'n',len(recs), 'types', ty.most_common(12))
