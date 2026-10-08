import sys, collections, numpy as np, re, zlib
sys.path.insert(0, 'src')
from db1dec import *
f = sys.argv[1]
data = load(f); db = Db(data); db.segment()
cov = np.zeros(len(data) // 4096 + 1, np.int64)
tot = 0
for s, r in db.runs:
    tot += s * len(r)
    np.add.at(cov, r // 4096, s)
print('len', len(data), 'in runs', tot, round(tot / len(data), 3))
# uncovered regions (4 KB blocks with < 5% coverage), group consecutive
low = cov < 200; regs = []; i = 0
while i < len(low):
    if low[i]:
        j = i
        while j < len(low) and low[j]: j += 1
        regs.append((i * 4096, (j - i) * 4096)); i = j
    else: i += 1
regs.sort(key=lambda x: -x[1]); print('largest uncovered', [(a, n) for a, n in regs[:8]], 'total', sum(n for a, n in regs))
for a, n in regs[:3]:
    blk = data[a:a + 256]; print(a, blk[:120])
# zlib streams
zs = [m.start() for m in re.finditer(rb'\x78[\x01\x5e\x9c\xda]', data[:])][:0]
# entropy of uncovered
for a, n in regs[:3]:
    b = np.frombuffer(data[a:a + min(n, 1 << 20)], np.uint8); h = np.bincount(b, minlength=256) / len(b); e = -(h[h > 0] * np.log2(h[h > 0])).sum(); print('entropy', a, round(e, 2))
