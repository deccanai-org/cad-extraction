"""before/after on data-3 models: kit_orig vs kit_patched convert_one (same python), compare per-part records."""
import json, os, subprocess, sys, gzip, collections, glob
HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.argv[1]; shas = sys.argv[2:]
J = {j['sha256']: j for j in json.load(open(os.path.join(HERE, '..', 'work', 'd3jobs.json')))}
os.makedirs(os.path.join(HERE, 'ab'), exist_ok=True)
rows = []
for s10 in shas:
    sha = next(k for k in J if k.startswith(s10)); job = J[sha]
    db1 = os.path.join(HERE, 'mf', sha[:10], os.path.basename(job['input_key']))
    if not os.path.exists(db1): print(s10, 'db1 missing'); continue
    res = {}
    for kit in ('kit_orig', 'kit_patched'):
        K = os.path.join(HERE, kit); out = os.path.join(HERE, 'ab', f'{sha[:10]}.{kit}')
        lay = out + '.lay.json'; json.dump(None, open(lay, 'w'))
        env = dict(os.environ, DB1_BOLTS='0')
        r = subprocess.run([PY, os.path.join(K, 'convert_one.py'), db1, out + '.ifc', os.path.join(K, 'tekla_profiles.json'), lay, out + '.json'], capture_output=True, text=True, env=env)
        st = json.load(open(out + '.json'))
        pl = json.load(gzip.open(out + '.json.parts.json.gz', 'rt')) if os.path.exists(out + '.json.parts.json.gz') else []
        res[kit] = (st, pl)
    (s0, p0), (s1, p1) = res['kit_orig'], res['kit_patched']
    def summ(pl):
        c = collections.Counter(); ex = collections.Counter()
        for seq, prof, cat, stt, how, guid, nc in pl:
            ex[cat] += 1
            if stt == 'written': c[cat] += 1
        return ex, c
    e0, w0 = summ(p0); e1, w1 = summ(p1)
    how0 = collections.Counter(h for *_, s_, h, g, n in [(r[0], r[1], r[2], r[3], r[4], r[5], r[6]) for r in p0] if s_ == 'written')
    changed = collections.Counter()
    b0 = {r[0]: r for r in p0}
    for r in p1:
        a = b0.get(r[0])
        if a and (a[3], a[4]) != (r[3], r[4]): changed[(a[1], a[3] + ':' + a[4], r[1], r[3] + ':' + r[4])] += 1
    row = dict(sha=sha[:10], status=(s0.get('status'), s1.get('status')), written=(s0.get('written'), s1.get('written')),
               expected=(dict(e0), dict(e1)), written_cat=(dict(w0), dict(w1)), null_records=s1.get('null_records'),
               changed=[(k, v) for k, v in changed.most_common(20)])
    rows.append(row); print(json.dumps(row, default=str), flush=True)
json.dump(rows, open(os.path.join(HERE, 'ab', 'ab_' + '_'.join(shas)[:60] + '.json'), 'w'), indent=1, default=str)
