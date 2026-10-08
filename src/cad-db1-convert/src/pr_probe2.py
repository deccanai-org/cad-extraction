import sys, re, collections, numpy as np; sys.path.insert(0,'src')
from db1dec import *
db=Db(load(sys.argv[1])); db.segment()
for S in (331, 317, 341, 265, 216, 69, 72, 56):
    recs=db.bystride.get(S)
    if recs is None: print(S,'none'); continue
    smp=recs[::max(1,len(recs)//4)][:4]
    print('== stride', S, len(recs))
    for o in smp:
        o=int(o); print('   ', [(m.start(), m.group().decode('latin1')) for m in re.finditer(rb'[\x20-\x7e]{3,}', db.b[o:o+S])][:8])
# names: count strings like profile names across the file
c=collections.Counter(m.group().decode() for m in re.finditer(rb'(?<=\x00)(?:W\d+X[\d.]+|HSS[\dX./]+|L\d[\dX./-]+|C\d+X[\d.]+|PL[\d./]+(?:X[\d./ ]+)?|BEAM|COLUMN|PLATE|BRACE)(?=\x00)', db.b))
print(c.most_common(20))
