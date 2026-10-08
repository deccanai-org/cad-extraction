#!/usr/bin/env python3
"""v5 vs v6 regression report from run_case results.
usage: report.py TESTSET.json V5DIR V6DIR [OUT.md]   (dirs hold <id16>/case.json + out.step.stats.json)"""
import sys, os, json, collections
ts = json.load(open(sys.argv[1])); d5, d6 = sys.argv[2], sys.argv[3]
out = open(sys.argv[4], 'w') if len(sys.argv) > 4 else sys.stdout


def load(d, i):
    try:
        c = json.load(open(os.path.join(d, i, 'case.json')))
    except Exception:
        return None
    try:
        c['stats'] = json.load(open(os.path.join(d, i, 'out.step.stats.json')))
    except Exception:
        c['stats'] = {}
    return c


def short(c):
    if c is None:
        return 'n/a'
    r = [x.split(':')[0] for x in (c.get('reasons') or []) + (c.get('issues') or [])]
    return '%s %s' % (c.get('class'), ','.join(sorted(set(r))) if r else '')


rows = []
for o in ts:
    i = o['id'][:16]
    a, b = load(d5, i), load(d6, i)
    if a is None and b is None:
        continue
    rows.append((o, a, b))
P = lambda *x: print(*x, file=out)
P('# ifc2step5 vs ifc2step6 regression (%d models)\n' % len(rows))
# class transitions by original reason group
trans = collections.Counter(); bygrp = collections.defaultdict(collections.Counter)
for o, a, b in rows:
    ca = a.get('class') if a else None; cb = b.get('class') if b else None
    trans[(ca, cb)] += 1
    bygrp[o['tag']][(ca, cb)] += 1
P('## class before -> after (all models)\n')
P('| v5 class | v6 class | models |\n|---|---|---|')
for (x, y), n in sorted(trans.items(), key=lambda t: (str(t[0][0]), str(t[0][1]))):
    P('| %s | %s | %d |' % (x, y, n))
P('\n## by test group (stratum of the live class-2 reason)\n')
P('| group | models | v5 class 1/2/3 | v6 class 1/2/3 |\n|---|---|---|---|')
for g, c in sorted(bygrp.items()):
    n = sum(c.values())
    c5 = collections.Counter(); c6 = collections.Counter()
    for (x, y), k in c.items():
        c5[x] += k; c6[y] += k
    P('| %s | %d | %d/%d/%d | %d/%d/%d |' % (g, n, c5[1], c5[2], c5[3], c6[1], c6[2], c6[3]))
# reasons before/after
r5 = collections.Counter(); r6 = collections.Counter()
for o, a, b in rows:
    for c, ctr in ((a, r5), (b, r6)):
        if c:
            for x in set(y.split(':')[0] for y in (c.get('reasons') or []) + (c.get('issues') or [])):
                ctr[x] += 1
P('\n## reasons (models carrying each)\n')
P('| reason | v5 | v6 |\n|---|---|---|')
for k in sorted(set(r5) | set(r6)):
    P('| %s | %d | %d |' % (k, r5[k], r6[k]))
P('\n## per model\n')
P('| group | id | schema | IFC MB | v5 class / reasons | v6 class / reasons | v5 STEP MB | v6 STEP MB | v5 s | v6 s | v6 read-back | v6 levels | v6 tags |')
P('|---|---|---|---|---|---|---|---|---|---|---|---|---|')
regress = []
for o, a, b in sorted(rows, key=lambda r: (r[0]['tag'], -r[0]['size'])):
    sa = (a or {}).get('step') or {}; sb = (b or {}).get('step') or {}
    st6 = (b or {}).get('stats') or {}
    P('| %s | %s | %s | %.1f | %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (
        o['tag'], o['id'][:12], o.get('schema'), o['size'] / 1e6, short(a), short(b),
        round((sa.get('bytes') or 0) / 1e6, 1) if a else '', round((sb.get('bytes') or 0) / 1e6, 1) if b else '',
        (a or {}).get('sec', ''), (b or {}).get('sec', ''), (b or {}).get('graded_by') or '',
        json.dumps(st6.get('levels')) if st6 else '', ', '.join('%s:%s' % kv for kv in sorted((st6.get('tags') or {}).items()))[:160]))
    if a and b and (a.get('class') or 9) < (b.get('class') or 9):
        regress.append((o, a, b))
P('\n## regressions (v6 class worse than v5): %d\n' % len(regress))
for o, a, b in regress:
    P('- %s %s: v5 %s -> v6 %s' % (o['tag'], o['id'][:16], short(a), short(b)))
