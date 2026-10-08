"""cmp.py TAG_U TAG_V OUT.json : per model u vs v (regress.py records + step_parts volumes): status, solids / valid / invalid, products,
written parts by source, grader stand-in tags (DB1_APPROX sections + hole_slotted_cut_round), per-part volume changes"""
import json, os, sys, gzip, glob, collections
R = '/opt/db1v/regress'; WK = '/opt/db1v/wk'
APPROX = {'parametric_angle', 'parametric_angle_equal', 'parametric_rhs', 'parametric_hss', 'catalog_upn_alias', 'parametric_grating', 'parametric_stud_shank', 'parametric_panel'}
def tags(rec):
    t = {}
    for s, n in ((rec.get('decoded') or {}).get('written_by_source') or {}).items():
        if s in APPROX and n: t['section_' + s] = n
    bs = (rec.get('convert') or {}).get('bolt_stats') or {}
    n = bs.get('slotted_bolts_cut_round') or bs.get('holes_in_slotted_groups_cut_round') or bs.get('slotted_groups_cut_round') or 0
    if n: t['hole_slotted_cut_round'] = n
    return t
def parts(tag, sha):
    p = os.path.join(WK, tag, sha[:12], 'step_parts.jsonl.gz'); d = {}
    if not os.path.exists(p): return None
    for l in gzip.open(p, 'rt'):
        try: r = json.loads(l)
        except Exception: continue
        k = (r.get('pid'), r.get('name'))
        d.setdefault(k, []).append(r)
    return d
U, V, OUT = sys.argv[1:4]; rows = []; agg = collections.Counter()
for f in sorted(glob.glob(f'{R}/{U}/*.json')):
    sha = os.path.basename(f)[:-5]; fv = f'{R}/{V}/{sha}.json'
    if not os.path.exists(fv): continue
    a = json.load(open(f)); b = json.load(open(fv))
    va, vb = a.get('validate') or {}, b.get('validate') or {}
    row = dict(id=sha, engine=a.get('engine'), status=[a.get('status'), b.get('status')],
               products=[va.get('products'), vb.get('products')], transferred=[va.get('transferred'), vb.get('transferred')],
               solids=[va.get('solids') or va.get('valid_solids_est'), vb.get('solids') or vb.get('valid_solids_est')],
               invalid=[va.get('invalid_solids_est', va.get('invalid')), vb.get('invalid_solids_est', vb.get('invalid'))],
               written=[sum(((a.get('decoded') or {}).get('written') or {}).values()), sum(((b.get('decoded') or {}).get('written') or {}).values())],
               tags_u=tags(a), tags_v=tags(b))
    bsa = (a.get('convert') or {}).get('bolt_stats') or {}; bsb = (b.get('convert') or {}).get('bolt_stats') or {}
    row['slots'] = {k: [bsa.get(k), bsb.get(k)] for k in ('slotted_holes_cut', 'slots_rotated', 'slotted_bolts_cut_round') if bsa.get(k) or bsb.get(k)}
    pa, pb = parts(U, sha), parts(V, sha)
    if pa is not None and pb is not None:
        ch = []; vol = [0.0, 0.0]
        for k in set(pa) | set(pb):
            x, y = pa.get(k) or [], pb.get(k) or []
            vx = sum(r.get('volume') or 0 for r in x); vy = sum(r.get('volume') or 0 for r in y)
            vol[0] += vx; vol[1] += vy
            if len(x) != len(y) or abs(vx - vy) > max(1e-6 * max(vx, vy), 1.0):
                ch.append((k[1], round(vx, 1), round(vy, 1)))
        row['parts_changed'] = len(ch); row['changed_examples'] = sorted(ch, key=lambda c: -abs(c[1] - c[2]))[:6]
        row['volume_total'] = [round(v, 1) for v in vol]
        row['parts_keys'] = [len(pa), len(pb)]
    worse = (b.get('status') != 'ok' and a.get('status') == 'ok') or (row['invalid'][1] or 0) > (row['invalid'][0] or 0) or \
            (row['transferred'][1] or 0) < (row['transferred'][0] or 0) or row['written'][1] < row['written'][0]
    row['worse'] = bool(worse)
    lost = sorted(set(row['tags_u']) - set(row['tags_v'])); row['tags_lost'] = lost
    for t in lost: agg['lost:' + t] += 1
    agg['models'] += 1; agg['worse'] += bool(worse); agg['ok_both'] += a.get('status') == b.get('status') == 'ok'
    rows.append(row)
json.dump(dict(summary=dict(agg), rows=rows), open(OUT, 'w'), indent=1, default=str)
print(dict(agg))
for r in rows: print(r['id'][:12], r['engine'], r['status'], 'inv', r['invalid'], 'trans', r['transferred'], 'chg', r.get('parts_changed'), 'lost', r['tags_lost'], 'WORSE' if r['worse'] else '')
