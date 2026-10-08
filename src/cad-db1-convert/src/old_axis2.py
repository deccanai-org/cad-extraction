import sys, re, glob, collections, numpy as np; sys.path.insert(0,'src')
import db1old
from db1dec import load
for f in sorted(glob.glob('pairs/data/old_*.db1')):
    data=load(f); eng=float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
    M, info, cut = db1old.read(data, eng)
    bad=collections.Counter((m['prof'] or '')[:3] for m in M if m['axis_ok'] is False)
    print(f.split('/')[-1], eng, 'parts', len(M), 'axis_agreement', info['axis_agreement'], 'disagree by prof prefix', bad.most_common(5))
