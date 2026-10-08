#!/usr/bin/env python3
"""Reviewer tool: for every part flagged by the ORIGINAL census+join, what happens after the patch:
still checked & passing (formula fixed) / no longer checked (check removed: openings, HSS/T v1, ...) / still flagged.
usage: perpart_fate.py WORKDIR OUT.json"""
import sys, json, gzip, importlib.util, collections, os
AUD = '/Users/dhiren/Downloads/Deccan/z3conv/_deepdive/classifier-audit'


def mod(p, n):
    s = importlib.util.spec_from_file_location(n, p); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m


oj = mod(f'{AUD}/orig_v4/grade_join.py', 'oj')
nj = mod('/Users/dhiren/Downloads/Deccan/z3conv/common/grade_join.py', 'nj')
W = sys.argv[1]


def pairs_of(J, src, step, new):
    """replicates join()'s pairing (gid / name), returns list of (p, s)"""
    sp_ok = [s for s in step if J.present(s)]
    pids = collections.Counter(s.get('pid') for s in sp_ok if s.get('pid'))
    gids = {p['gid'] for p in src if p.get('gid')}
    hit = sum(1 for g in gids if g in pids)
    mode = 'gid' if gids and hit >= 0.5 * min(len(gids), max(1, len(pids))) else ('name' if src and sp_ok else 'none')
    pairs = []
    if mode == 'gid':
        bypid = {}
        for s in sp_ok:
            if s.get('pid'):
                bypid.setdefault(s['pid'], s)
        for p in src:
            s = bypid.get(p.get('gid'))
            if s is not None:
                pairs.append((p, s, 'gid'))
    elif mode == 'name':
        pool = collections.defaultdict(list)
        for s in sp_ok:
            pool[J.canon(s.get('name'))].append(s)
        name_count = collections.Counter(J.canon(p.get('name')) for p in src)
        groups = collections.defaultdict(list)
        for p in src:
            nm = J.canon(p.get('name'))
            lst = pool.get(nm)
            if lst:
                s = lst.pop(); groups[nm].append((p, s))
        census_v2 = bool(src) and all((p.get('cv') or 1) >= 2 for p in src)
        for nm, lst in groups.items():
            if name_count[nm] == 1:
                pairs.append(lst[0] + ('unique',))
            elif new and census_v2 and len(lst) == name_count[nm] and not pool.get(nm):
                ps = sorted((p for p, _ in lst), key=lambda p: nj.expected_volume(p) or 0.0)
                ss = sorted((s for _, s in lst), key=lambda s: s.get('volume') or 0.0)
                pairs.extend((a, b, 'grouped') for a, b in zip(ps, ss))
    return mode, pairs


def ratio(p, s, new):
    v = s.get('volume')
    e = nj.expected_volume(p) if new else (p.get('an') or p.get('q'))
    if not v or not e or e <= 0 or (s.get('solids') or 0) == 0:
        return None
    return v / e


ids = sorted({f.split('.')[0] for f in os.listdir(f'{W}/recensus') if f.endswith('.src_parts.jsonl.gz')})
out = []
agg = collections.Counter(); removed_ratios = []; removed_kinds = collections.Counter()
for i in ids:
    sp = f'{W}/stepparts/{i}.step_parts.jsonl.gz'; o = f'{W}/origcensus/{i}.src_parts.jsonl.gz'; n = f'{W}/recensus/{i}.src_parts.jsonl.gz'
    if not (os.path.exists(sp) and os.path.exists(o) and os.path.exists(n)):
        continue
    step = oj.load(sp); so = oj.load(o); sn = nj.load(n)
    mo, po = pairs_of(oj, so, step, False)
    mn, pn = pairs_of(nj, sn, step, True)
    newp = {}
    for p, s, how in pn:
        newp.setdefault(p.get('gid'), []).append((p, s, how))
    srcn = {p.get('gid'): p for p in sn}
    fate = collections.Counter()
    for p, s, how in po:
        r = ratio(p, s, False)
        if r is None or abs(r - 1) <= 0.05 or (p.get('an') and p.get('pt') in ('Circle', 'CircleHollow')):
            continue
        g = p.get('gid'); pn_ = srcn.get(g)
        cand = newp.get(g) or []
        r2 = None
        for p2, s2, how2 in cand:
            r2 = ratio(p2, s2, True)
        if r2 is not None and abs(r2 - 1) <= 0.05:
            k = 'fixed_pass'
        elif r2 is not None:
            k = 'still_flagged'
        else:
            if pn_ is None:
                k = 'removed_no_part'
            elif pn_.get('op'):
                k = 'removed_openings'
            elif not (nj.expected_volume(pn_)):
                k = 'removed_no_expected'
            else:
                k = 'removed_not_paired'
            removed_ratios.append(round(r, 3)); removed_kinds[(k, p.get('pt') or p.get('qk'), p['cls'])] += 1
        fate[k] += 1
    agg.update(fate)
    out.append({'id': i, 'mode': [mo, mn], 'fate': dict(fate)})
json.dump({'agg': dict(agg), 'removed_kinds': {str(k): v for k, v in removed_kinds.most_common()}, 'models': out}, open(sys.argv[2], 'w'), indent=0)
print('agg', dict(agg))
import statistics
rr = sorted(removed_ratios)
if rr:
    print('removed ratios n', len(rr), 'min', rr[0], 'p5', rr[len(rr)//20], 'median', statistics.median(rr), 'p95', rr[int(len(rr)*0.95)], 'max', rr[-1])
    print('removed with ratio > 1.05:', sum(1 for x in rr if x > 1.05), ' < 0.5:', sum(1 for x in rr if x < 0.5))
print(removed_kinds.most_common(25))
