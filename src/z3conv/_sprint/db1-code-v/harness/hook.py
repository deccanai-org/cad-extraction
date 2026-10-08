"""hook.py KITDIR : export slot-decoding state of db1step (new + old engines) into module globals V2 / OLDH (harness only)"""
import sys, os
p = os.path.join(sys.argv[1], 'db1step.py'); s = open(p).read()
a = "            BG, HP, pst = db1bolts2.plan(bgroups, parts, REGION, blinks, std_fn, db1bolts.washer_t)\n"
assert s.count(a) == 1
s = s.replace(a, a + "            V2.update(bgroups=bgroups, blinks=blinks, HP=HP, BG=BG, parts=parts, M=M, db=db)\n")
b = "    # pass 2: write\n    for m in M:\n        if m.get('cut'):\n            why['cut_part_excluded'] += 1; continue\n"
assert s.count(b) == 1, s.count(b)
s = s.replace(b, "    V2.update(V2SLOT=V2SLOT, bseq=bseq, eng=_eng2)\n" + b)
c = "        # axial fit: shift each bolt along its axis so that its shank covers the plies it passes through"
assert s.count(c) == 1
s = s.replace(c, "        OLDH.update(BL=BL, SLOT_SET=SLOT_SET, REL10L=REL10L, M=M, PLY=PLY, eng=eng_s, slot_why=dict(slot_why), ROTP=locals().get('ROTP') or {})\n" + c)
d = "def _convert(db1_path, out_ifc, cat, layout=None, variants=(), allow_full=True):"
assert s.count(d) == 1
s = s.replace(d, "V2 = {}\nOLDH = {}\n" + d)
open(p, 'w').write(s)
p2 = os.path.join(sys.argv[1], 'db1old.py'); s2 = open(p2).read()
a2 = "    attrs = {}\n    for q in at_off:\n"
assert s2.count(a2) == 1
s2 = s2.replace(a2, "    attrs = {}\n    global ATTR_OFF, RAW\n    ATTR_OFF = {int(I[q]): int(q) for q in at_off}; RAW = data\n    for q in at_off:\n")
open(p2, 'w').write(s2); print('hooked')
