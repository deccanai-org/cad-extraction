import sys, re, collections, numpy as np; sys.path.insert(0,'src')
import db1old
from db1dec import load
f=sys.argv[1]; data=load(f); eng=float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
o=db1old.Old(data); I=o.I_all; D=o.D_all; N=len(I)-400
# attr table (stride 373 rule from db1old)
av=np.zeros(N,bool); M=N-380
av[:M]=(I[:M]>0)&(I[4:M+4]>=0)&(I[4:M+4]<=100)&(I[72:M+72]>=0)&(I[72:M+72]<=64)
pr=o.u8[124:124+M]; av[:M]&=(pr>=32)&(pr<=126)
at=o.runs(av,373); ids=np.unique(I[at]); print(eng, 'attr records', len(at), 'ids', len(ids), 'sample', [o.cstr(int(q)+124,20) for q in at[:5]])
# positions where an attr id appears (int32 at any offset), excluding the attr records themselves
K=np.sort(ids); pos=np.nonzero(np.isin(I[:N], K))[0]
atset=set(int(x) for x in at)
pos=[int(p) for p in pos if p not in atset]
print('refs to attr ids', len(pos))
gaps=collections.Counter(np.diff(pos).tolist()).most_common(8); print('gaps between refs', gaps)
# for the dominant gap (record stride), look at the layout of one record around a ref
s=gaps[0][0]
p=pos[len(pos)//2]
print('dominant stride', s)
for base in range(p-40, p+s, 4):
    print(f'{base-p:+4d} i={int(I[base]):>12d} d={D[base]:.6g}')
