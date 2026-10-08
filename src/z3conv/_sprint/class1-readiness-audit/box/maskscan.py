"""maskscan.py SHA12,... : old-engine bolt-group attribute records (part_attr stride 373, obj_type 10): per byte offset, value
distribution for slotted groups (string fields 1/2 != 0) vs round groups, per model. Looks for Tekla's 'slotted holes in parts' selection:
a field that is 0 on round groups, and on slotted groups non-zero where Tekla's own NC files show slotted holes (5a2284473e4e: 150 NC
parts with slotted BO holes) but 0 where they show none (6b87b724b554 / 6eabb07e7145: no slotted BO hole in 56 / 219 NC parts)."""
import sys, gzip, json, collections, numpy as np
sys.path.insert(0, 'kit_k')
import db1old
out = {}
for s12 in sys.argv[1].split(','):
    import glob
    p = glob.glob(f'src/{s12}*.db1')[0]
    data = open(p, 'rb').read()
    if data[:2] == b'\x1f\x8b':
        import zlib
        data = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(data)
    o = db1old.Old(data); N = len(o.I_all) - 400; I = o.I_all; M = N - 380
    av = np.zeros(N, bool)
    av[:M] = (I[:M] > 0) & (I[4:M + 4] >= 0) & (I[4:M + 4] <= 100) & (I[72:M + 72] >= 0) & (I[72:M + 72] <= 64)
    pr = o.u8[124:124 + M]; av[:M] &= (pr >= 32) & (pr <= 126)
    at = o.runs(av, 373)
    byte = {'slot': collections.defaultdict(collections.Counter), 'round': collections.defaultdict(collections.Counter)}
    n = collections.Counter()
    for q in at:
        q = int(q)
        if int(I[q + 4]) != 10: continue
        f = o.cstr(q + 124, 62).split('/')
        if len(f) != 11: continue
        try: sl = float(f[1]) != 0 or float(f[2]) != 0
        except ValueError: continue
        k = 'slot' if sl else 'round'; n[k] += 1
        rec = o.u8[q:q + 373]
        for off in list(range(8, 124)) + list(range(186, 270)) + list(range(292, 373)):
            byte[k][off][int(rec[off])] += 1
    out[s12] = {'n': dict(n), 'slot': {o_: dict(c.most_common(6)) for o_, c in byte['slot'].items()},
                'round': {o_: dict(c.most_common(6)) for o_, c in byte['round'].items()}}
# candidate offsets: round groups always 0 in every model; slot groups non-zero share differs strongly between the NC-slotted model
# (first id) and the NC-round models (others)
ids = sys.argv[1].split(',')
cand = []
for off in list(range(8, 124)) + list(range(186, 270)) + list(range(292, 373)):
    r0 = all(set(out[m]['round'].get(off, {0: 1})) <= {0} for m in ids if out[m]['n'].get('round'))
    def nz(m):
        c = out[m]['slot'].get(off, {}); t = sum(c.values()) or 1
        return 1 - c.get(0, 0) / t
    a = nz(ids[0]); b = max(nz(m) for m in ids[1:])
    rz = {m: round(1 - out[m]['round'].get(off, {}).get(0, 0) / (sum(out[m]['round'].get(off, {}).values()) or 1), 3) for m in ids}
    cand.append((round(a - b, 3), off, round(a, 3), round(b, 3), r0, rz, out[ids[0]]['slot'].get(off), [out[m]['slot'].get(off) for m in ids[1:]]))
cand.sort(key=lambda c: -c[0])
json.dump({'models': {m: {'n': v['n']} for m, v in out.items()}, 'candidates': cand}, open('maskscan.json', 'w'), indent=1, default=str)
print({m: v['n'] for m, v in out.items()}); print('candidates (offset, nonzero share slotted-NC model, max share NC-round models, values):')
for c in cand[:30]: print(c)
