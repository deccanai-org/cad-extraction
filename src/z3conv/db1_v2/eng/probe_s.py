import sys, json, collections
sys.path.insert(0, 'src'); sys.path.insert(0, '.')
import db1dec; from db1dec import *
import attrlink
L = json.load(open('src/layouts.json')); VA = [v['layout'] for v in L.values() if v.get('layout')]
f, eng = sys.argv[1:3]
data = load(f); db, pts, cs, lay = decode(data, L[eng]['layout'], VA, False)
M = members(db, pts, cs, lay); db.find_cut_links(M)
ev = attrlink.evidence(db, lay, M); print(f.split('/')[-1], ev, 'confirmed', attrlink.confirmed(ev))
