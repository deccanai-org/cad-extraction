"""Count bolt-record candidates in member files with the plausibility check relaxed (any diameter 0.25-2.5 in, any
grip/length), to see whether nominal stacks lack records in the source or the decoder rejects them.
usage: bolt_records_relaxed.py <decode dir> <job> [max members]"""
import sys, os, struct, collections, numpy as np
sys.path.insert(0, sys.argv[1])
import bolts as BR
job = sys.argv[2]; lim = int(sys.argv[3]) if len(sys.argv) > 3 else 10 ** 9
names = sorted(int(f) for f in os.listdir(os.path.join(job, 'mem')) if f.isdigit())[:lim]
strict = 0; relaxed = collections.Counter(); ex = []
for n in names:
    b = open(os.path.join(job, 'mem', str(n)), 'rb').read()
    strict += len(BR.member_bolts(job, n, (np.eye(3), np.zeros(3))))
    seen = set()
    for al in range(8):
        k = (len(b) - al) // 8
        if k < 16: continue
        d = np.frombuffer(b[al:al + 8 * k], '>f8').astype(float)
        with np.errstate(all='ignore'):
            Wn = np.lib.stride_tricks.sliding_window_view(d, 12)
            ok = np.ones(len(Wn), bool)
            for r in range(3): ok &= np.abs((Wn[:, 3 * r:3 * r + 3] ** 2).sum(1) - 1) < 1e-6
        for i in np.where(ok)[0]:
            R = d[i:i + 9].reshape(3, 3)
            if not np.isfinite(R).all() or np.abs(R @ R.T - np.eye(3)).max() > 1e-6: continue
            q = al + 8 * int(i)
            if q + 160 > len(b) or any(abs(q - s) < 128 for s in seen): continue
            dia, L = struct.unpack('>2d', b[q + 96:q + 112]); grip = struct.unpack('>d', b[q + 120:q + 128])[0]
            f = struct.unpack('>4f', b[q + 96:q + 112])
            if 0.25 <= dia <= 2.5 and 0 < L < 100:
                seen.add(q); relaxed[('f64', round(dia, 4), 'grip<L' if 0 < grip < L else 'grip?')] += 1
                if len(ex) < 6: ex.append((n, q, round(dia, 4), round(L, 4), round(grip, 4)))
            elif 0.25 <= f[0] <= 2.5 and 0 < f[1] < 100:
                seen.add(q); relaxed[('f32', round(f[0], 4), round(f[1], 3))] += 1
print('members', len(names), 'strict records', strict)
print('relaxed candidates', sum(relaxed.values()), relaxed.most_common(15))
print(ex)
