"""unlinked_occ.py KITDIR DB1 [N] : old engines - for cut parts with no type-11 relation, print every raw occurrence of their id
(outside their own part record) with the surrounding int32s; and for type-11 relation children that are not decoded parts,
the same (what kind of record is the child?)"""
import sys, os, re, collections, numpy as np
KIT = sys.argv[1]; sys.path.insert(0, KIT)
import db1old, db1prof
from db1dec import load
f = sys.argv[2]; NSHOW = int(sys.argv[3]) if len(sys.argv) > 3 else 8
data = load(f); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
M, info, cut_rel = db1old.read(data, eng)
M = [m for m in M if not db1prof.is_null_record(m)]
byp = {m['pid']: m for m in M}; own = {m['off'] for m in M}
o = db1old.Old(data); I = o.I_all; D = o.D_all; N = len(I) - 80
linked = {c for v in cut_rel.values() for c in v}
cuts = [m for m in M if m['cut']]
un = [m for m in cuts if m['pid'] not in linked]
def cls(i):
    m = byp.get(i)
    return 'none' if m is None else ('cut' if m['cut'] else ('bolt' if m['bolt'] else 'part:' + str(m['prof'])[:14]))
def show(i, tag):
    occ = [int(q) for q in np.nonzero(I[80:N] == i)[0] + 80]
    print('  %s id %d (%s) occurrences %d' % (tag, i, cls(i), len(occ)))
    for q in occ[:8]:
        ints = [int(I[q + k]) for k in range(-16, 28, 4)]
        print('     @%d own=%s pre[q-13]=%d pre[q-1]=%d ints[-16..+24] %s classes %s' % (q, q in own, data[q - 13], data[q - 1], ints,
              [cls(v) if 0 < v < 2**31 and v in byp else '' for v in ints]))
print('==', os.path.basename(f)[:16], eng, 'cuts', len(cuts), 'linked', len(cuts) - len(un), 'unlinked', len(un))
for m in un[:NSHOW]:
    print(' UNLINKED cut', m['pid'], m['prof'], 'L', round(m['L'], 1), 'O', np.round(m['O'], 1).tolist(), 'attr', m['attr'], 'form', m['form'])
    show(m['pid'], 'cut')
nd = sorted({c for v in cut_rel.values() for c in v if c not in byp})
print(' type-11 children not decoded:', len(nd), '| parents not decoded:', len([p for p in cut_rel if p not in byp]))
for c in nd[:NSHOW]:
    par = [p for p, cs in cut_rel.items() if c in cs]
    print(' CHILD-NOT-DECODED', c, 'parents', par[:3], [cls(p) for p in par[:3]])
    show(c, 'child')
