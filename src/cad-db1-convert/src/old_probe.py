import sys, re, collections, numpy as np; sys.path.insert(0,'src')
import db1old
from db1dec import load
f=sys.argv[1]; data=load(f); eng=float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
o=db1old.Old(data); I=o.I_all; D=o.D_all; N=len(I)-400
print(f.split('/')[-1], eng, len(data))
# point-like tables: id>0, three finite doubles (xyz) at some offset k, per stride s
for s in range(25, 80):
    for k in (4, 8, 12):
        v=np.zeros(N,bool); M=N-s-8
        v[:M]=(I[:M]>0)
        for j in range(3):
            d=D[k+8*j:M+k+8*j]; v[:M]&=np.isfinite(d)&(np.abs(d)<1e7)&((d==0)|(np.abs(d)>1e-6))
        r=o.runs(v,s,minrun=8)
        if len(r)>500: print('  point-like stride',s,'xyz@',k,'records',len(r))
