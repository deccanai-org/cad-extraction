#!/usr/bin/env python3
"""Join a source inventory (ifc_census parts) with a STEP check (step_check parts) -> grading signals.
Used by the IFC / DB1 workers and the grade worker; the class itself is assigned centrally by the index builder.

  join(src_parts, step_parts) -> {
    mode: gid (STEP PRODUCT.id = source GlobalId) | name (multiset of names; older writers) | none,
    expected {category: n}, matched {category: n}, coverage {member, connection, other, all},
    step_parts, step_parts_unmatched, surface_parts,
    volume {checked, within_5pct, outside_5pct, outside_curved, median, p5, p95, worst[...]},
    standins [{type, real_type, count}], missing_examples [[gid, class, name]] }
usage (CLI): grade_join.py SRC.parts.jsonl.gz STEP.parts.jsonl.gz OUT.json"""
import sys, json, gzip, collections, statistics

CURVED = ('Circle', 'CircleHollow')
PHYS_CATS = ('member', 'connection', 'rebar', 'building', 'mep', 'proxy', 'spatial', 'other')


def load(path):
    out = []
    with gzip.open(path, 'rt') as f:
        for line in f:
            if line.strip():
                out.append(json.loads(line))
    return out


def present(sp):
    return (sp.get('solids') or 0) > 0 or (sp.get('faces') or 0) > 0


def join(src, step, tol=0.05):
    exp = collections.Counter(p['cat'] for p in src)
    sp_ok = [s for s in step if present(s)]
    pids = collections.Counter(s.get('pid') for s in sp_ok if s.get('pid'))
    gids = {p['gid'] for p in src if p.get('gid')}
    hit = sum(1 for g in gids if g in pids)
    mode = 'gid' if gids and hit >= 0.5 * min(len(gids), max(1, len(pids))) else ('name' if src and sp_ok else 'none')
    matched = collections.Counter(); pairs = []; missing = []
    if mode == 'gid':
        bypid = {}
        for s in sp_ok:
            if s.get('pid'):
                bypid.setdefault(s['pid'], s)
        used = set()
        for p in src:
            s = bypid.get(p.get('gid'))
            if s is not None:
                matched[p['cat']] += 1; pairs.append((p, s)); used.add(p.get('gid'))
            elif len(missing) < 25:
                missing.append([p.get('gid'), p['cls'], p.get('name')])
        unmatched = sum(1 for s in sp_ok if s.get('pid') not in gids)
    elif mode == 'name':
        pool = collections.defaultdict(list)
        for s in sp_ok:
            pool[s.get('name') or ''].append(s)
        name_count = collections.Counter(p.get('name') or '' for p in src)
        for p in src:
            nm = p.get('name') or ''
            lst = pool.get(nm)
            if lst:
                s = lst.pop()
                matched[p['cat']] += 1
                if name_count[nm] == 1:
                    pairs.append((p, s))                # unique names only: safe for the per-part volume check
            elif len(missing) < 25:
                missing.append([p.get('gid'), p['cls'], p.get('name')])
        unmatched = sum(len(v) for v in pool.values())
    else:
        unmatched = len(sp_ok)
    cov = {}
    for c in ('member', 'connection'):
        cov[c] = round(matched[c] / exp[c], 4) if exp[c] else None
    other_exp = sum(v for k, v in exp.items() if k not in ('member', 'connection'))
    other_m = sum(v for k, v in matched.items() if k not in ('member', 'connection'))
    cov['other'] = round(other_m / other_exp, 4) if other_exp else None
    tot = sum(exp.values())
    cov['all'] = round(sum(matched.values()) / tot, 4) if tot else None
    # per-part volume / weight check
    ratios = []; curved_out = 0; out_ = 0; worst = []; checked = 0
    for p, s in pairs:
        v = s.get('volume')
        e = p.get('an') or p.get('q')
        if not v or not e or e <= 0 or (s.get('solids') or 0) == 0:
            continue
        checked += 1
        r = v / e
        ratios.append(r)
        if abs(r - 1) > tol:
            if p.get('an') and p.get('pt') in CURVED:
                curved_out += 1
            else:
                out_ += 1
            worst.append([round(r, 4), p.get('gid'), p['cls'], p.get('name'), 'analytic' if p.get('an') else p.get('qk')])
    worst.sort(key=lambda x: -abs(x[0] - 1))
    vol = {'checked': checked, 'outside_5pct': out_, 'outside_curved': curved_out, 'within_5pct': checked - out_ - curved_out}
    if ratios:
        rs = sorted(ratios)
        vol.update(median=round(statistics.median(rs), 4), p5=round(rs[int(0.05 * (len(rs) - 1))], 4), p95=round(rs[int(0.95 * (len(rs) - 1))], 4))
    vol['worst'] = worst[:12]
    st = collections.Counter((p.get('standin'), p['cls']) for p in src if p.get('standin'))
    return {'mode': mode, 'expected': dict(exp), 'matched': dict(matched), 'coverage': cov, 'step_parts': len(step),
            'step_parts_present': len(sp_ok), 'step_parts_unmatched': unmatched,
            'surface_parts': sum(1 for s in sp_ok if (s.get('solids') or 0) == 0), 'volume': vol,
            'standins': [{'type': k[0], 'real_type': k[1], 'count': n} for k, n in st.most_common()],
            'missing_examples': missing}


if __name__ == '__main__':
    r = join(load(sys.argv[1]), load(sys.argv[2]))
    json.dump(r, open(sys.argv[3], 'w'))
    print(json.dumps(r))
