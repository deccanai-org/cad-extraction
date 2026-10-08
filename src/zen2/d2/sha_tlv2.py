import sys, struct, collections, olefile
SRC='/work/in/src/'
o=olefile.OleFileIO(SRC+sys.argv[1])
def recs(b):
    k=8; out=[]
    while k+6<=len(b):
        t,ln=struct.unpack_from('<HI',b,k); out.append((t,b[k+6:k+6+ln])); k+=6+ln
    return out
for n in sys.argv[2].split(','):
    b=o.openstream(n).read(); R=recs(b)
    lens=collections.defaultdict(collections.Counter)
    for t,p in R: lens[t][len(p)]+=1
    print('==',n)
    for t,c in sorted(lens.items(), key=lambda x:-sum(x[1].values()))[:14]:
        ex=[p for tt,p in R if tt==t][0]
        print(t, dict(c.most_common(4)), ex[:20].hex(), '...', ' '.join('%.4g'%v for v in struct.unpack_from('<%dd'%min(6,(len(ex)-18)//8), ex, 18)) if len(ex)>=26 else '')
