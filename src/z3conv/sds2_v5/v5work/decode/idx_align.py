"""Find where mem/<n> content appears inside mem_idx, to learn slot size/base and what extra the idx holds."""
import os, sys, re
d = os.path.join(sys.argv[1], "mem")
idx = open(os.path.join(d, "mem_idx"), "rb").read()
for n in (1, 2, 3, 100, 5000):
    m = open(os.path.join(d, str(n)), "rb").read()
    for off, ln in ((0x48, 24), (0xd0, 24), (0x158, 24)):
        k = m[off:off + ln]
        hits = [h.start() for h in re.finditer(re.escape(k), idx)] if any(k) else []
        print(f"mem/{n} bytes@{off:#x}: idx hits {hits[:4]}", "slot=%s rem=%s" % tuple(divmod(hits[0] - off, 2494)) if hits else "")
# show strings around a type label in one slot
slot = 2
base = None
p = idx.find(b"COLUMN")
print("first COLUMN at", p, "mod 2494 =", p % 2494)
for s in range(1, 6):
    seg = idx[s * 2494:(s + 1) * 2494]
    print(s, [(hex(x.start()), x.group().decode()) for x in re.finditer(rb"[A-Za-z0-9#_ .\-]{3,}", seg)][:12])
