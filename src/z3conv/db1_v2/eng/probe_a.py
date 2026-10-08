import sys, json, time, collections, numpy as np
sys.path.insert(0, 'src')
from db1dec import *
L = json.load(open('src/layouts.json')); VA = [v['layout'] for v in L.values() if v.get('layout')]
f = sys.argv[1]; eng = sys.argv[2] if len(sys.argv) > 2 else None
data = load(f); print('len', len(data), data[:60])
db = Db(data); db.segment()
c = collections.Counter({s: len(r) for s, r in db.bystride.items()}); print('top strides', c.most_common(30))
