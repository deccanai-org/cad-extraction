"""Pick plate pieces never referenced by a mem material block, then search every job folder (except subm/)
for their ids as i32 BE; report where references live."""
import os, sys, struct, re, collections, random
from instances import material_instances
from piece_table import read_pieces, kind

job = sys.argv[1]
pieces = read_pieces(job)
used = set()
for n in (int(x) for x in os.listdir(os.path.join(job, "mem")) if x.isdigit()):
    for sid, M, o in material_instances(job, n, pieces)[1]:
        used.add(sid)
orphans = [k for k, p in pieces.items() if kind(p) == "plate" and k not in used and k > 1000]
random.seed(1)
pick = random.sample(orphans, 6)
print(f"plates: {sum(kind(p)=='plate' for p in pieces.values())}, referenced by material blocks: {sum(1 for k in used if kind(pieces[k])=='plate')}, orphans sampled: {[(k, pieces[k]['name']) for k in pick]}")
pats = {struct.pack(">i", k): k for k in pick}
rx = re.compile(b"|".join(re.escape(p) for p in pats))
hits = collections.Counter(); ex = []
for d in os.listdir(job):
    dp = os.path.join(job, d)
    if not os.path.isdir(dp) or d == "subm": continue
    for f in os.listdir(dp):
        fp = os.path.join(dp, f)
        try: b = open(fp, "rb").read()
        except OSError: continue
        for m in rx.finditer(b):
            hits[d] += 1
            if len(ex) < 20: ex.append((f"{d}/{f}", m.start(), pats[m.group()], struct.unpack(">6i", b[m.start() - 8:m.start() + 16]) if m.start() >= 8 and m.start() + 16 <= len(b) else None))
print("hits by folder:", hits.most_common())
for e in ex: print("  ", e)
