"""List old-engine cut parts (ANTIMATERIAL) whose cutting body is not built, with the reason and the parent part."""
import sys, os, re, json, numpy as np
H = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(H, '..', os.environ.get('KIT', 'kit_snapshot')))
import db1old, db1step
from db1dec import load
cat = json.load(open(os.path.join(H, '..', 'kit_snapshot', 'tekla_profiles.json')))
for f in sys.argv[1:]:
    data = load(f); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
    if eng >= 7.5: continue
    M, info, cut_rel = db1old.read(data, eng)
    parent = {c: p for p, cs in cut_rel.items() for c in cs}
    byp = {m['pid']: m for m in M}
    n = 0
    for m in M:
        if not m.get('cut'): continue
        kind, v, how = db1step.section_for(m['prof'], cat)
        why = None
        if kind is None and v == 'contour_plate':
            thick = float(re.findall(r'[\d.]+', m['prof'])[0])
            if not (m.get('old_poly') and len(m['old_poly']) >= 3): why = 'contour_plate_no_outline (npoly=%s)' % (len(m['old_poly']) if m.get('old_poly') else 0)
        elif kind is None: why = v
        if why:
            n += 1
            p = byp.get(parent.get(m['pid']))
            print(os.path.basename(f)[:12], 'cut pid', m['pid'], repr(m['prof']), 'mat', m['mat'], 'L', round(m['L'], 1), 'form', m['form'], '->', why,
                  '| parent', parent.get(m['pid']), p['prof'] if p else None)
    print('==', os.path.basename(f)[:12], 'cut parts', sum(1 for m in M if m.get('cut')), 'unbuilt', n)
