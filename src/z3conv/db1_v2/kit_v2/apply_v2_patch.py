"""apply_v2_patch.py KIT_DIR OUT_DIR : take the builder's current kit (db1step.py, db1bolts.py, ...) and apply the v2 new-engine bolt
patch, so v2 always tracks the latest builder code. Idempotent; fails loudly if an anchor is missing."""
import sys, os, re, shutil
kit, out = sys.argv[1:3]
os.makedirs(out, exist_ok=True)
s = open(os.path.join(kit, 'db1step.py')).read()
start = s.index('def _convert(')
end = s.index('def convert_old(')
sec = s[start:end]
MARK = "    # ---- v2: bolt groups of the record-discovered engines"
A = MARK if MARK in sec else "    cut_body = {}\n    for m in M:\n        if m.get('cut'):"     # re-apply: replace an earlier v2 block
Z = "    st['parts_list'] = plist\n    st['cuts_applied'] = applied\n"
a = sec.index(A); z = sec.index(Z)
NEW = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'v2_convert_block.py')).read()
sec = sec[:a] + NEW + sec[z:]
s = s[:start] + sec + s[end:]
open(os.path.join(out, 'db1step.py'), 'w').write(s)
b = open(os.path.join(kit, 'db1bolts.py')).read()
V2B = '\n\n# ---- v2 (db1 v2 patch)'
if V2B in b:                                   # re-apply on an already patched db1bolts: drop the earlier v2 tail
    b = b[:b.index(V2B)].rstrip('\n') + '\n'
else:
    assert 'def standard_geometry(standard, d):' in b, 'db1bolts.standard_geometry anchor missing'
    b = b.replace('def standard_geometry(standard, d):', 'def _standard_geometry_tables(standard, d):', 1)
    b = b.rstrip('\n') + '\n'
b += '''


# ---- v2 (db1 v2 patch): Tekla's own bolt-assembly dimensions harvested from 2,500 Tekla IFC exports come before the standards
# tables, for every engine (old-engine bolts_of and the 7.5x-8.x writer both call standard_geometry)
_ASTM_PREFIX = ('A325', 'A490', 'A307', 'F1852', 'F2280', 'F3125')


def standard_geometry(standard, d):
    """-> geometry dict (db1bolts format). Tekla harvest (exact standard name / verified alias / name prefix) first; else the standards
    tables, where ASTM sizes take Tekla's own F436 washer (harvested from the same nominal size) when available."""
    sg = _standard_geometry_tables(standard, d)
    try:
        import db1bolts2
        tg = db1bolts2.tekla_geometry(standard, d)
        if not tg and sg and abs(sg.get('d', d) - d) > 0.06:
            # old engines store inch bolts metric-rounded (16 for 5/8 in): Tekla's dims at the table's true diameter
            tg = db1bolts2.tekla_geometry(standard, sg['d'])
            if tg: tg['mapping'] = f"{d:g} mm stored -> {tg['mapping']}"
    except Exception:
        tg = None
    s = (standard or '').upper().replace(' ', '')
    if tg:
        tg['source'] = 'tekla_harvest'
        if tg.get('hole_clearance') is None:
            tg['hole_clearance'] = (1 / 16 * _IN) if s.startswith(_ASTM_PREFIX) else clearance(d)
        return tg
    if sg and 'ASTM' in sg.get('family', ''):
        try:
            import db1bolts2
            w = db1bolts2.tekla_geometry('A325N', sg['d'])
            if w and w.get('washer_od') and w.get('washer_t'):
                sg = dict(sg, washer_od=w['washer_od'], washer_t=w['washer_t'], source='table+tekla_washer',
                          family=sg['family'] + ' + Tekla F436 washer (IFC harvest)')
        except Exception:
            pass
    return sg
'''
for fn in ('def washer_dims(b):', 'def washer_exact(b):'):
    i = b.find(fn)
    if i < 0: continue
    if b.find("'tekla_harvest', 'table+tekla_washer'", i, i + 700) > 0: continue
    j = b.find("sg.get('source') == 'model_catalog'", i)
    if j > 0 and j - i < 600:
        b = b[:j] + "sg.get('source') in ('model_catalog', 'tekla_harvest', 'table+tekla_washer')" + b[j + len("sg.get('source') == 'model_catalog'"):]
open(os.path.join(out, 'db1bolts.py'), 'w').write(b)
print('patched ->', out)
