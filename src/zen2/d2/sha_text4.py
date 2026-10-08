import sys, struct, collections, olefile, re, math, pymupdf
sys.path.insert(0,'/work/2d')
from sha_text3 import recs, find_str, find_pos
o=olefile.OleFileIO(SRC:='/work/in/src/'+sys.argv[1]) if False else olefile.OleFileIO('/work/in/src/'+sys.argv[1])
want=sys.argv[3].split('|')
for n in sys.argv[2].split(','):
    for t,p in recs(o.openstream(n).read()):
        if t&0x7fff!=77: continue
        r=find_str(p)
        if not r: continue
        k,L,s=r
        if s.strip() not in want: continue
        q=find_pos(p,k+2+2*L)
        e=q[0]+32 if q else k+2+2*L
        print(repr(s), 'hdr', struct.unpack_from('<IIIHI',p,0), 'pre', p[18:k].hex(), 'pos', q[1] if q else None, 'gap', p[k+2+2*L:q[0]].hex() if q else '', 'after', p[e:].hex())
