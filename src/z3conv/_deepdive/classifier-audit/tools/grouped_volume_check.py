#!/usr/bin/env python3
"""Independent per-part volume check for name-mode joins (no unique names needed).
For every part name: sort the source expected volumes (analytic `an`, else quantity `q`) and the STEP solid volumes, pair them
in order (optimal 1-D assignment), count pairs outside +-tol. Prints one JSON line per model.
usage: grouped_volume_check.py DETDIR ID [ID ...]   (DETDIR/<id>.src_parts.jsonl.gz + DETDIR/<id>.step_parts.jsonl.gz)"""
import sys, json, gzip, collections, statistics, os
CURVED = ('Circle', 'CircleHollow')


def load(p):
    with gzip.open(p, 'rt') as f:
        return [json.loads(l) for l in f if l.strip()]


def check(src, step, tol=0.05):
    exp = collections.defaultdict(list); got = collections.defaultdict(list)
    for p in src:
        e = p.get('an') or p.get('q')
        if e and e > 0:
            exp[p.get('name') or ''].append((e, p.get('pt') in CURVED and bool(p.get('an')), p.get('cls'), p.get('an') is not None))
    for s in step:
        if (s.get('solids') or 0) > 0 and s.get('volume') is not None:
            got[s.get('name') or ''].append(s['volume'])
    pairs = 0; out = 0; out_curved = 0; ratios = []; worst = []
    for nm, el in exp.items():
        gl = sorted(got.get(nm, []))
        el = sorted(el)
        if len(gl) != len(el):          # unequal group: pair only if same count (else ambiguous)
            continue
        for (e, curved, cls, an), v in zip(el, gl):
            pairs += 1; r = v / e; ratios.append(r)
            if abs(r - 1) > tol:
                if curved: out_curved += 1
                else:
                    out += 1; worst.append([round(r, 4), nm, cls, 'an' if an else 'q'])
    worst.sort(key=lambda x: -abs(x[0] - 1))
    res = {'pairs': pairs, 'outside': out, 'outside_curved': out_curved}
    if ratios:
        rs = sorted(ratios)
        res.update(median=round(statistics.median(rs), 4), p5=round(rs[int(0.05 * (len(rs) - 1))], 4), p95=round(rs[int(0.95 * (len(rs) - 1))], 4))
    res['worst'] = worst[:8]
    return res


if __name__ == '__main__':
    d = sys.argv[1]
    for i in sys.argv[2:]:
        a, b = os.path.join(d, i + '.src_parts.jsonl.gz'), os.path.join(d, i + '.step_parts.jsonl.gz')
        if not (os.path.exists(a) and os.path.exists(b)):
            print(json.dumps({'id': i, 'error': 'missing detail'})); continue
        print(json.dumps(dict(id=i, **check(load(a), load(b)))))
