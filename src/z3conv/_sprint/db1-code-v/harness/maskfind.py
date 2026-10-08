"""maskfind.py DIR.. : new-engine slot ply-selection field search. Truth mask per group = bits (ply rank from the head) of the bolted parts
Tekla NC1 shows slotted; only groups whose every bolted part has a single NC label. Scores every byte offset of the bolt attribute
record (u8 / i32) by equality with the truth mask, per (engine, stride)."""
import json, glob, sys, collections, struct
T = collections.defaultdict(list)
for d in sys.argv[1:]:
    for f in sorted(glob.glob(d + '/*.json')):
        j = json.load(open(f)); e = j.get('engine'); ga = j.get('gattr') or {}
        byg = collections.defaultdict(list)
        for r in j.get('rows', []): byg[r['g']].append(r)
        for g, rs in byg.items():
            a = ga.get(str(g)) or ga.get(g)
            if not a or not a.get('full'): continue
            if any(len(r['truth']) != 1 or r['truth'][0] not in ('slot', 'round') or r.get('plyrank') is None for r in rs): continue
            if len({r['plyrank'] for r in rs}) != len(rs): continue
            m = sum(1 << r['plyrank'] for r in rs if r['truth'] == ['slot'])
            T[(e, a['S'])].append((m, len(rs), bytes.fromhex(a['full']), f.split('/')[-1][:12], rs[0].get('mask')))
for (e, S), L in sorted(T.items()):
    print(e, 'S', S, 'groups with full truth', len(L), 'models', len({x[3] for x in L}), 'truth masks', collections.Counter(x[0] for x in L).most_common(6),
          'current decode == truth:', sum(1 for x in L if x[4] is not None and (x[4] & ((1 << min(x[1], 5)) - 1)) == x[0]))
    sc = []
    for k in range(S - 3):
        nz = [x for x in L if x[0]]; z = [x for x in L if not x[0]]
        f8 = lambda x: (x[2][k] & ((1 << min(x[1], 5)) - 1)) == x[0]
        def f32(x):
            v = struct.unpack_from('<i', x[2], k)[0]
            return 0 <= v < 64 and (v & ((1 << min(x[1], 5)) - 1)) == x[0]
        sc.append((sum(map(f32, nz)), sum(map(f32, z)), sum(map(f8, nz)), sum(map(f8, z)), k))
    sc.sort(reverse=True)
    print('   nonzero-truth groups', sum(1 for x in L if x[0]), '| best (i32 nz, i32 zero, u8 nz, u8 zero, offset):', sc[:8])
