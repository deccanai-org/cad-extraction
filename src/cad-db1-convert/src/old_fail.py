"""why does an old-format file give 0 parts? try each part/attr table width around the known ones"""
import sys, re, collections, numpy as np; sys.path.insert(0,'src')
import db1old
from db1dec import load
f=sys.argv[1]; data=load(f); eng=float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
o=db1old.Old(data); I=o.I_all; N=len(I)-400
print(f, eng, 'bytes', len(data), 'banner', data[:40])
# part_attr: count validating runs for strides near 373 using the documented field tests
for s in range(300, 460):
    av=np.zeros(N,bool); M=N-s-8
    av[:M]=(I[:M]>0)&(I[4:M+4]>=0)&(I[4:M+4]<=100)&(I[72:M+72]>=0)&(I[72:M+72]<=64)
    pr=o.u8[124:124+M]; av[:M]&=(pr>=65)&(pr<=90)
    r=o.runs(av,s)
    if len(r)>20: print(' attr stride',s,'records',len(r))
