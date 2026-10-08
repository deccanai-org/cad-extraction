import sys, re, numpy as np; sys.path.insert(0,'src')
from db1dec import load
b=load(sys.argv[1])
for h in (46730548, 46102637, 46730494):
    k=h-16
    print(h, 'key', int.from_bytes(b[k:k+4],'little'), 'bytes before key:', b[k-13:k].hex(' '), '| key..string', b[k:h].hex(' '), repr(b[h:h+24]))
    print('   ints at key-13..', [int.from_bytes(b[k-13+i:k-9+i],'little',signed=True) for i in (0,4)], 'byte key-5..key-1', b[k-5:k].hex(' '))
