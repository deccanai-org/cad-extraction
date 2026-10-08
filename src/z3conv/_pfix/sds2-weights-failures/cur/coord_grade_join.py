#!/usr/bin/env python3
"""Join a source inventory (ifc_census parts) with a STEP check (step_check parts) -> grading signals.
Used by the IFC / DB1 workers and the grade worker; the class itself is assigned centrally by the index builder.

  join(src_parts, step_parts) -> {
    mode: gid (STEP PRODUCT.id = source GlobalId) | name (multiset of names; older writers) | none,
    expected {category: n}, matched {category: n}, coverage {member, connection, other, all},
    step_parts, step_parts_unmatched, surface_parts,
    volume {checked, within_5pct, outside_5pct, outside_curved, outside_curved_gross, median, p5, p95, worst[...]},
    standins [{type, real_type, count}], missing_examples [[gid, class, name]] }
usage (CLI): grade_join.py SRC.parts.jsonl.gz STEP.parts.jsonl.gz OUT.json"""
import sys, json, gzip, math, collections, statistics

CURVED = ('Circle', 'CircleHollow')
CURVED_BAND = (0.90, 1.05)     # tessellated round sections: measured 0.958..1.021 over 12,580 parts (62 models, data-3)
OLD_CENSUS_BAD_AN = ('RectangleHollow', 'T')   # census v1 area formula ignored HSS corner radii / WT root fillets (-9.5..+7 %)


def cov4(m, e):
    """coverage rounded DOWN to 4 decimals: 1 missing part in > 20,000 must not round up to 1.0"""
    return math.floor(m / e * 1e4) / 1e4 if e else None


def expected_volume(p):
    """expected mm3 of a census part, or None when the census version cannot be trusted for it: census v1 (no `cv`) had no
    opening check and wrong hollow-rectangle / T areas, so its analytic value is dropped for those profile types"""
    an = p.get('an')
    if an and (p.get('cv') or 1) < 2 and p.get('pt') in OLD_CENSUS_BAD_AN:
        an = None
    return an or p.get('q')
import re as _re
_X2 = _re.compile(r'\\X2\\([0-9A-Fa-f]+)\\X0\\')


def canon(name):
    """name as written by any ifc2step writer version vs the raw IFC name: decode STEP string escapes, drop quote characters and
    whitespace (writers differ in apostrophe handling), lower-case, 60-character prefix"""
    s = str(name or '')
    s = _X2.sub(lambda m: ''.join(chr(int(m.group(1)[i:i + 4], 16)) for i in range(0, len(m.group(1)), 4)), s)
    s = s.replace('\\\\', '\\')
    s = _re.sub(r"[\s'\"`]", '', s).lower()
    return s[:60]
PHYS_CATS = ('member', 'connection', 'rebar', 'building', 'mep', 'proxy', 'spatial', 'other')


def load(path):
    out = []
    with gzip.open(path, 'rt') as f:
        for line in f:
            if line.strip():
                out.append(json.loads(line))
    return out


def load_bytes(b):
    if b[:2] == b'\x1f\x8b':
        b = gzip.decompress(b)
    return [json.loads(l) for l in b.decode().splitlines() if l.strip()]


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
            pool[canon(s.get('name'))].append(s)
        name_count = collections.Counter(canon(p.get('name')) for p in src)
        groups = collections.defaultdict(list)
        for p in src:
            nm = canon(p.get('name'))
            lst = pool.get(nm)
            if lst:
                s = lst.pop()
                matched[p['cat']] += 1
                groups[nm].append((p, s))
            elif len(missing) < 25:
                missing.append([p.get('gid'), p['cls'], p.get('name')])
        unmatched = sum(len(v) for v in pool.values())
        # per-part volume check: a unique name pairs directly. A repeated name (SDS/2 piecemarks, Tekla 'BEAM' / 'PLATE') pairs
        # its expected and its STEP volumes in sorted order (optimal 1-D assignment) when every source part of that name found a
        # STEP part and none is left over - only with a census v2 inventory (openings / profile corner radii handled)
        census_v2 = bool(src) and all((p.get('cv') or 1) >= 2 for p in src)
        for nm, lst in groups.items():
            if name_count[nm] == 1:
                pairs.append(lst[0])
            elif census_v2 and len(lst) == name_count[nm] and not pool.get(nm):
                ps = sorted((p for p, _ in lst), key=lambda p: expected_volume(p) or 0.0)
                ss = sorted((s for _, s in lst), key=lambda s: s.get('volume') or 0.0)
                pairs.extend(zip(ps, ss))
    else:
        unmatched = len(sp_ok)
    tot_exp = sum(exp.values())
    if mode == 'name' and tot_exp and sum(matched.values()) < 0.98 * min(tot_exp, len(sp_ok)) and len(sp_ok) >= 0.98 * tot_exp:
        # names did not survive the older writer: coverage by part count (every category at the overall ratio), flagged
        f = min(1.0, len(sp_ok) / tot_exp)
        matched = collections.Counter({k: int(round(v * f)) for k, v in exp.items()})
        mode = 'count'; missing = []; pairs = []
    cov = {}
    for c in ('member', 'connection'):
        cov[c] = cov4(matched[c], exp[c])
    other_exp = sum(v for k, v in exp.items() if k not in ('member', 'connection'))
    other_m = sum(v for k, v in matched.items() if k not in ('member', 'connection'))
    cov['other'] = cov4(other_m, other_exp)
    tot = sum(exp.values())
    cov['all'] = cov4(sum(matched.values()), tot)
    # per-part volume / weight check
    ratios = []; curved_out = 0; curved_gross = 0; out_ = 0; worst = []; checked = 0; slivers = 0
    for p, s in pairs:
        v = s.get('volume')
        e = expected_volume(p)
        if not v or not e or e <= 0 or (s.get('solids') or 0) == 0:
            continue
        bb = s.get('bbox')
        if e < 1000.0 or (isinstance(bb, (list, tuple)) and len(bb) == 6 and min(bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]) < 1.0):
            slivers += 1                     # G4: < 1 000 mm3 or thinner than 1 mm (100x the 0.01 mm STEP grid): not volume-checked
            continue
        checked += 1
        r = v / e
        ratios.append(r)
        if abs(r - 1) > tol:
            if p.get('an') and p.get('pt') in CURVED:
                curved_out += 1
                if not CURVED_BAND[0] <= r <= CURVED_BAND[1]:
                    curved_gross += 1                   # beyond tessellation loss: wrong length / section
            else:
                out_ += 1
            worst.append([round(r, 4), p.get('gid'), p['cls'], p.get('name'), 'analytic' if p.get('an') else p.get('qk')])
    worst.sort(key=lambda x: -abs(x[0] - 1))
    vol = {'checked': checked, 'outside_5pct': out_, 'outside_curved': curved_out, 'outside_curved_gross': curved_gross,
           'within_5pct': checked - out_ - curved_out, 'slivers_not_checked': slivers}
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
