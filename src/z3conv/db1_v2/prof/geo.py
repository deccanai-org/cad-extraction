import sys, re, numpy as np, collections, json
import db1old
from db1dec import load
PAT = re.compile(r'^(D\d{4}|ROD\d{4}|PD\d+-\d+|EPD|ELD|/|0\*|5$)')
for p in sys.argv[1:]:
    data = load(p); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
    M, info, cut = db1old.read(data, eng)
    print('==', p, eng, len(M))
    sel = [m for m in M if m['prof'] and PAT.match(m['prof'])]
    for m in sel:
        print('  ', m['prof'], 'L', round(m['L'], 1), 'O', np.round(m['O']).tolist(), 'x', np.round(m['x'], 3).tolist(), 'form', m.get('form'), 'npoly', len(m.get('old_poly') or []), 'cut', m['cut'])
