import sys, json, collections, numpy as np
sys.path.insert(0, 'src'); sys.path.insert(0, '.')
import db1dec; from db1dec import *
import guid2
L = json.load(open('src/layouts.json')); VA = [v['layout'] for v in L.values() if v.get('layout')]
f, eng = sys.argv[1:3]
data = load(f); db, pts, cs, lay = decode(data, L[eng]['layout'], VA, False)
M = members(db, pts, cs, lay); print('members', len(M))
gm, info = guid2.guid_map(data, [m['seq'] for m in M]); print(info)
