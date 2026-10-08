# secscore.py DECODE JOBDIR: calibrate()'s own section-field search with the 2494-B point offsets fixed (for jobs whose
# member files carry no work point key); also checks beam geometry plausibility
import sys, os, struct, collections
sys.path.insert(0, sys.argv[1]); job = sys.argv[2]
import sds2job as S
import numpy as np
sh = S.read_shapes(job)
md = os.path.join(job, 'mem'); idx = open(os.path.join(md, 'mem_idx'), 'rb').read()
ids = sorted(int(n) for n in os.listdir(md) if n.isdigit())
slot, toff, p1, p2 = 2494, 0x988, 0x112, 0x172
beams = [n for n in ids if S._ascii(idx[n * slot + toff:n * slot + toff + 20]) == 'BEAM'][:3000]
cols = [n for n in ids if S._ascii(idx[n * slot + toff:n * slot + toff + 20]) == 'COLUMN']
res = []
for so in range(p2 + 0x30, p2 + 0xA0, 2):
    vals = [struct.unpack('>h', idx[n * slot + so:n * slot + so + 2])[0] for n in beams]
    ok = [v for v in vals if v in sh and sh[v].family in S.SHAPE_FAMILIES]
    res.append((len(ok) / len(vals) * min(len(set(ok)), 20), hex(so), len(ok), len(vals), len(set(ok))))
res.sort(reverse=True)
print('beams', len(beams), 'columns', len(cols)); print('top section-field candidates (score, offset, mapped, n, distinct):', res[:4])
so = 0x1D4
fam = collections.Counter(sh[struct.unpack('>h', idx[n * slot + so:n * slot + so + 2])[0]].name.split('X')[0][:3] for n in beams if struct.unpack('>h', idx[n * slot + so:n * slot + so + 2])[0] in sh)
print('beam sections @0x1D4 (name prefix):', fam.most_common(8))
cs = collections.Counter(sh[struct.unpack('>h', idx[n * slot + so:n * slot + so + 2])[0]].name for n in cols if struct.unpack('>h', idx[n * slot + so:n * slot + so + 2])[0] in sh)
print('column sections @0x1D4:', cs.most_common(5))
# geometry: beams horizontal-ish, columns vertical
def vec(n):
    s = idx[n * slot:(n + 1) * slot]
    a = np.array(struct.unpack('>3d', s[p1:p1 + 24])); b = np.array(struct.unpack('>3d', s[p2:p2 + 24])); return b - a
bv = np.array([vec(n) for n in beams]); cv = np.array([vec(n) for n in cols])
L = np.linalg.norm(bv, axis=1); Lc = np.linalg.norm(cv, axis=1)
print('beam length in: median %.1f, p5 %.1f, p95 %.1f; |dz|/L < 0.05: %d/%d' % (np.median(L), np.percentile(L, 5), np.percentile(L, 95), int(np.sum(np.abs(bv[:, 2]) / np.maximum(L, 1e-9) < 0.05)), len(L)))
print('column length in: median %.1f; |dz|/L > 0.95: %d/%d' % (np.median(Lc), int(np.sum(np.abs(cv[:, 2]) / np.maximum(Lc, 1e-9) > 0.95)), len(Lc)))
rolls = [struct.unpack('>d', idx[n * slot + 0x1DA:n * slot + 0x1DA + 8])[0] for n in beams]
print('roll @0x1DA finite & |r|<=7: %d/%d, nonzero %d' % (sum(1 for r in rolls if r == r and abs(r) <= 7), len(rolls), sum(1 for r in rolls if r == r and abs(r) <= 7 and r != 0)))
