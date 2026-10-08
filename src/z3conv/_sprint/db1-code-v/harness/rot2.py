"""rot2.py OUTDIR : within each model, compare the full part-attr record + member record of slotted groups whose slot direction agrees
with NC vs is rotated 90 deg: byte positions (4-byte ints / bytes) that separate the two sets"""
import json, glob, sys, collections, struct
for f in sorted(glob.glob(sys.argv[1] + '/*.json')):
    j = json.load(open(f)); ga = j.get('gattr') or {}
    lab = collections.defaultdict(set)
    for r in j.get('rows', []):
        if r['pred'] is not True or r['truth'] != ['slot']: continue
        pa = r['palong']; nd = set(r['ncdir'])
        if not (pa > 0.99 or pa < 0.01) or len(nd) != 1: continue
        lab[r['g']].add(('True' if pa > 0.99 else 'False') in nd)
    ok = [g for g, s in lab.items() if s == {True}]; bad = [g for g, s in lab.items() if s == {False}]
    if not bad: continue
    print(f.split('/')[-1][:12], j['engine'], 'groups ok', len(ok), 'bad', len(bad), 'mixed', sum(1 for s in lab.values() if len(s) > 1))
    for src in ('full', 'mrec'):
        R = {g: bytes.fromhex(ga[str(g)][src]) for g in ok + bad if str(g) in ga and ga[str(g)].get(src)}
        if not R: continue
        n = min(len(b) for b in R.values())
        for k in range(0, n - 3):
            vo = {struct.unpack_from('<i', R[g], k)[0] for g in ok if g in R}; vb = {struct.unpack_from('<i', R[g], k)[0] for g in bad if g in R}
            if vo and vb and not (vo & vb) and len(vo) <= 3 and len(vb) <= 3:
                print('  ', src, '@%d' % k, 'ok', sorted(vo)[:3], 'bad', sorted(vb)[:3])
        for k in range(0, n):
            vo = {R[g][k] for g in ok if g in R}; vb = {R[g][k] for g in bad if g in R}
            if vo and vb and not (vo & vb) and len(vo) <= 2 and len(vb) <= 2:
                print('   byte', src, '@%d' % k, 'ok', sorted(vo), 'bad', sorted(vb))
