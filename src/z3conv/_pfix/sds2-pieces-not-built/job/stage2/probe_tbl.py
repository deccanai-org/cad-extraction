import sys, os, json, collections, struct
sys.path.insert(0, sys.argv[1])
import numpy as np
import piece_table as PT
from piece_table import read_pieces, slot_size, LAYOUTS
W = '/work/agentwork/sds2-pieces-not-built/jobs/'
for jn in sys.argv[2:]:
    job = W + jn
    b = open(os.path.join(job, 'subm', 'subm_idx'), 'rb').read()
    print('=====', jn, 'subm_idx bytes', len(b), 'slot_size', slot_size(b), 'layouts', list(LAYOUTS))
    P = read_pieces(job)
    c = collections.Counter()
    for sid, p in P.items():
        c[(p['L'] > 0, p['W'] > 0, p['T'] > 0, p['wt'] > 0, round(p['T'], 3) if p['T'] == 12.0 else 'x')] += 1
    print(' L>0,W>0,T>0,wt>0,T==12:', c.most_common(8))
    ex = [(sid, p['name'], round(p['L'], 3), round(p['W'], 3), round(p['T'], 3), round(p['wt'], 3), p['sec']) for sid, p in list(P.items())[:15]]
    for e in ex: print('  ', e)
    # alternative layouts: score names
    for key, Lo in LAYOUTS.items():
        S = Lo['slot']; o = Lo['name']
        ok = 0; n = 0
        for k in range(1, min(len(b) // S, 3000), 7):
            s = b[k * S + o:k * S + o + 24].split(b'\0')[0]
            n += 1
            if s and all(32 <= ch < 127 for ch in s): ok += 1
        print('   layout', key, 'slot', S, 'printable names', ok, '/', n, ' divides', (len(b) - 256) % S == 0)
