import sys, re, numpy as np; sys.path.insert(0,'src')
from db1dec import load
b=load(sys.argv[1])
for pat in (b'80/180/8\x00', b'80/180/10\x00', b'80/6\x00', b'HEA', b'IPE'):
    hits=[m.start() for m in re.finditer(re.escape(pat), b)][:12]
    print(pat, len(hits))
    for h in hits[:8]:
        s=h
        while s>0 and 32<=b[s-1]<127: s-=1
        print('   ', h, repr(b[s:h+len(pat)]), 'prev bytes', b[s-16:s].hex())
