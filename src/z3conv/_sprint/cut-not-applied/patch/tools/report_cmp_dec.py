"""report_cmp_dec.py : decode-level part counts per profile bucket (before / after the patch) vs the model folder's own Tekla part list"""
import sys, os, json, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from report_parse import pick, bucket
tot = collections.Counter(); out = []
for d in sorted(os.listdir('reports')):
    f, rows = pick(os.path.join('reports', d))
    if not rows: continue
    fb, fa = f'dec/before/{d}.json', f'dec/after/{d}.json'
    if not (os.path.exists(fb) and os.path.exists(fa)): continue
    B, A = json.load(open(fb)), json.load(open(fa))
    if 'parts' not in B: continue
    rep = collections.Counter(); repw = collections.Counter()
    for mk, prof, q, L, w in rows: rep[bucket(prof)] += q; repw[bucket(prof)] += w
    def cnt(D):
        c = collections.Counter()
        for pid, prof, cut, bolt, ot, L, mat, ax in D['parts']:
            if cut or bolt or ax is False or not prof: continue
            c[bucket(prof)] += 1
        return c
    cb, ca = cnt(B), cnt(A)
    keys = set(rep) | set(cb) | set(ca)
    changed = [k for k in keys if cb[k] != ca[k]]
    eb = sum(abs(cb[k] - rep[k]) for k in changed); ea = sum(abs(ca[k] - rep[k]) for k in changed)
    tb = sum(abs(cb[k] - rep[k]) for k in keys); ta = sum(abs(ca[k] - rep[k]) for k in keys)
    exact_b = sum(1 for k in rep if cb[k] == rep[k]); exact_a = sum(1 for k in rep if ca[k] == rep[k])
    tot['models'] += 1; tot['err_changed_before'] += eb; tot['err_changed_after'] += ea; tot['err_all_before'] += tb; tot['err_all_after'] += ta
    tot['report_parts'] += sum(rep.values()); tot['exact_buckets_before'] += exact_b; tot['exact_buckets_after'] += exact_a; tot['report_buckets'] += len(rep)
    better = ea < eb; worse = ea > eb
    tot['better'] += better; tot['worse'] += worse; tot['same'] += (not better and not worse)
    print('%s report %s rows %d parts %d | changed buckets %d: |model-report| %d -> %d | all buckets %d -> %d | exact buckets %d -> %d of %d'
          % (d, os.path.basename(f), len(rows), sum(rep.values()), len(changed), eb, ea, tb, ta, exact_b, exact_a, len(rep)))
    for k in sorted(changed, key=lambda k: -abs(cb[k] - ca[k]))[:8]:
        print('      %-22s report %5d  before %5d  after %5d' % (k[:22], rep[k], cb[k], ca[k]))
print('TOTAL', dict(tot))
