"""Old-engine parts whose profile name parses to an implausible size: what are they (length, material, name, cut?, neighbours)."""
import sys, os, re, json, collections, numpy as np
H = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(H, '..', 'kit_patched'))
import db1old, db1step
from db1dec import load
cat = json.load(open(os.path.join(H, '..', 'kit_snapshot', 'tekla_profiles.json')))
for f in sys.argv[1:]:
    data = load(f); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
    if eng >= 7.5: continue
    M, info, cut_rel = db1old.read(data, eng)
    for m in M:
        if m.get('cut') or m.get('bolt'): continue
        k, v, how = db1step.section_for(m['prof'], cat)
        if k is None and v in ('implausible_profile', 'unresolved', 'profile_without_size'):
            print(os.path.basename(f)[:12], eng, repr(m['prof']), v, 'mat', m['mat'], 'ben', m['ben'], 'L', round(m['L'], 1), 'O', np.round(m['O']).tolist(), 'x', np.round(m['x'], 3).tolist(), 'form', m['form'], 'npoly', len(m['old_poly'] or []))
