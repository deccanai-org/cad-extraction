"""Explore mem_idx / mem_ctl / mem_list layout."""
import re, os, sys, collections
d = os.path.join(sys.argv[1], "mem")
N = len([n for n in os.listdir(d) if n.isdigit()])
b = open(os.path.join(d, "mem_idx"), "rb").read()
print("mem_idx", len(b), "per member", len(b) / N, len(b) / (N + 1))
pos = [m.start() for m in re.finditer(rb"COLUMN|BEAM\x00|BRACE", b)]
print("type hits", len(pos))
df = collections.Counter(pos[i + 1] - pos[i] for i in range(len(pos) - 1))
print("spacing", df.most_common(8))
ms = [(hex(m.start()), m.group().decode()) for m in re.finditer(rb"[ -~]{3,}", b[:30000])]
print(ms[:60])
for n in ("mem_ctl", "mem_list"):
    x = open(os.path.join(d, n), "rb").read()
    print(n, len(x), "per member", len(x) / N)
    print("  ", x[:192].hex())
