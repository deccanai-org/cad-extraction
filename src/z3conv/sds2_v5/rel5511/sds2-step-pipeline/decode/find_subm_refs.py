"""Where are subm ids referenced? Search mem/<n> files for big-endian i32/i16 subm ids; report offset patterns."""
import os, sys, struct, collections, re

job = sys.argv[1]
md = os.path.join(job, "mem")
targets = [int(x) for x in sys.argv[2].split(",")]
hits = collections.defaultdict(list)
for n in os.listdir(md):
    if not n.isdigit(): continue
    b = open(os.path.join(md, n), "rb").read()
    for t in targets:
        for pat, w in ((struct.pack(">i", t), "i32"),):
            for m in re.finditer(re.escape(pat), b):
                hits[t].append((int(n), m.start(), w, len(b)))
for t in targets:
    print(t, hits[t][:12])
# offset pattern relative to the 0x2A0 + k*538 block grid
c = collections.Counter()
for t, hs in hits.items():
    for n, off, w, L in hs:
        if off >= 0x2A0:
            c[(off - 0x2A0) % 538] += 1
print("offset within 538-block:", c.most_common(8))
