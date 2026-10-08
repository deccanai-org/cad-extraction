"""unwritten_parents.py ID... : cut parts linked to a parent that is not written: what is the parent?"""
import sys, os, re, json, gzip, glob, collections
W = '/work/agentwork/cut-not-applied'; KIT = os.environ.get('KIT', W + '/kitnp'); sys.path.insert(0, KIT)
import db1old
from db1dec import load
for ID in sys.argv[1:]:
    data = load(f'{W}/src/{ID}.db1'); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
    M, info, cut_rel = db1old.read(data, eng); byp = {m['pid']: m for m in M}
    pl = {p[0]: p for p in json.load(gzip.open(f'{W}/convall/kitnp/{ID}/convert.json.parts.json.gz', 'rt'))}
    c = collections.Counter(); ex = collections.Counter()
    for par, cs in cut_rel.items():
        p = pl.get(par)
        if p and p[3] == 'written': continue
        m = byp.get(par)
        if m is None: k = 'parent_not_decoded'
        elif m.get('cut'): k = 'parent_is_cut_part(%s)' % ('operative' if m.get('mat') != 'ANTIMATERIAL' else 'ANTIMATERIAL')
        elif m.get('bolt'): k = 'parent_is_bolt'
        elif p: k = 'parent_skipped:' + str(p[4])
        else: k = 'parent_dropped(axis/null)'
        c[k] += len(cs); ex[(k, (m or {}).get('prof'))] += len(cs)
    print('==', ID, eng, dict(c)); print('    ', ex.most_common(8))
