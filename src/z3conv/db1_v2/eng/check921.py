import sys, json, time, collections, numpy as np, re
sys.path.insert(0, 'src')
import db1dec; from db1dec import *
L = json.load(open('src/layouts.json')); VA = [v['layout'] for v in L.values() if v.get('layout')]
for f in sys.argv[1:]:
    t = time.time(); data = load(f)
    eng = re.search(rb'(\d+\.\d+)', data[:16]).group(1).decode()
    db, pts, cs, lay = decode(data, L[eng]['layout'], VA, False)
    M = members(db, pts, cs, lay) if lay and lay.get('csys') is not None else []
    nm = [m for m in M if not m['cut']]
    print(f.split('/')[-1], eng, 'sec', round(time.time() - t), 'members', len(M), 'with profile', sum(1 for m in M if m['prof']),
          'fast', lay.get('fast'), 'semi', lay.get('semi'), 'axis', db1dec._axis_agreement(db, pts, lay, M) if M else None, 'webv', db1dec._web_vertical(M) if M else None,
          'top', collections.Counter(m['prof'] for m in nm).most_common(6), flush=True)
