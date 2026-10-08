"""Find subm ids by (section name, length) and every reference to them (i32 BE) in mem/*, with context."""
import os, sys, re, struct, collections

job, name, length = sys.argv[1], sys.argv[2], float(sys.argv[3])
member = int(sys.argv[4]) if len(sys.argv) > 4 else None
sb = open(os.path.join(job, "subm", "subm_idx"), "rb").read()
N = (len(sb) - 256) // 852
ids = []
for k in range(1, N):
    s = sb[k * 852:(k + 1) * 852]
    if re.match(rb"[ -~]*", s[0x12E:0x15E]).group().decode() == name and abs(struct.unpack(">d", s[0x16C:0x174])[0] - length) < 0.05:
        ids.append(k)
print(f"subm ids for {name} L={length}: {len(ids)} e.g. {ids[:12]}")
md = os.path.join(job, "mem")
targets = {struct.pack(">i", i): i for i in ids}
files = [str(member)] if member else [f for f in os.listdir(md) if f.isdigit()]
offs = collections.Counter(); shown = 0
for f in files:
    b = open(os.path.join(md, f), "rb").read()
    for pat, sid in targets.items():
        for m in re.finditer(re.escape(pat), b):
            o = m.start()
            around = struct.unpack(">8i", b[o - 16:o + 16]) if o >= 16 and o + 16 <= len(b) else None
            offs[(o - 0x296) % 658] += 1
            if shown < 25:
                print(f"  mem/{f} @{o} subm {sid}  i32 ctx {around}")
                shown += 1
print("offset mod 658 (from 0x296):", offs.most_common(6))
