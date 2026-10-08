import sys, struct, re
sys.path.insert(0,'/work/2d')
import sha2dxf as S
dec=S.Decoder('/work/in/src/'+sys.argv[1])
for storage, idxs in (('', [331,303,394,329,4,0x118,0xd2]), ('JSite4756',[331,303,394,329,4,0xd2,0x118])):
    st=dec.styles(storage)
    for i in idxs:
        if i not in st: print(storage or 'root', i, 'missing'); continue
        t,p=st[i]
        names=[m.decode('utf-16le') for m in re.findall(rb'((?:[\x20-\x7e]\x00){2,40})', p)]
        dbl=[(o,round(struct.unpack_from('<d',p,o)[0]*1000,4)) for o in range(16,len(p)-7) if 1e-4<abs(struct.unpack_from('<d',p,o)[0])<0.05]
        refs=[(o,struct.unpack_from('<H',p,o)[0]) for o in (40,42,44,46,48) if o+2<=len(p)]
        print(storage or 'root', i, 'type', t, len(p), names, 'dbl(mm)', dbl[:6], 'u16@40..', refs)
