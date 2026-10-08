"""prefix byte of decoded old-engine part records (and of their attr / csys / point records): live (4) vs other."""
import sys, os, re, collections, numpy as np
H = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(H, '..', 'kit_patched'))
import db1old
from db1dec import load
for f in sys.argv[1:]:
    data = load(f); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
    if eng >= 7.5: continue
    M, info, cut_rel = db1old.read(data, eng)
    c = collections.Counter(data[m['off'] - 1] for m in M)
    odd = [(m['pid'], m['prof'], m['mat'], data[m['off'] - 1]) for m in M if data[m['off'] - 1] != 4][:5]
    print(os.path.basename(f)[:12], eng, 'parts', len(M), 'part prefix', c.most_common(5), 'salvaged', info['salvaged'], 'odd', odd)
