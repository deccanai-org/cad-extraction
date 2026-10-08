#!/usr/bin/env python3
"""cmp_rv.py LABEL_A LABEL_B [...] : per model, class / tags / read-back and per-part (by product id) solids + volume, A vs each other label"""
import sys, os, json, gzip, math, collections
W = '/work/agentwork/ifc-verification-residue-review/w'
labels = sys.argv[1:]
ids = sorted(set.intersection(*[set(os.listdir(os.path.join(W, l))) for l in labels if os.path.isdir(os.path.join(W, l))]))
def load(l, i):
    d = os.path.join(W, l, i); o = {}
    try: o['case'] = json.load(open(os.path.join(d, 'case.json')))
    except Exception: o['case'] = {}
    try: o['chk'] = json.load(open(os.path.join(d, 'out.step.check.json')))
    except Exception: o['chk'] = {}
    parts = {}
    p = os.path.join(d, 'step_parts.jsonl.gz')
    if os.path.exists(p):
        op = gzip.open if open(p, 'rb').read(2) == b'\x1f\x8b' else open
        for line in op(p, 'rt'):
            try: r = json.loads(line)
            except Exception: continue
            k = r.get('pid') or r.get('name') or ('#%s' % r.get('i'))
            e = parts.setdefault(k, {'n': 0, 'solids': 0, 'valid': 0, 'vol': 0.0, 'faces': 0, 'shells': 0})
            e['n'] += 1; e['solids'] += r.get('solids') or 0; e['valid'] += r.get('valid') or 0; e['vol'] += r.get('volume') or 0.0
            e['faces'] += r.get('faces') or 0; e['shells'] += r.get('shells') or 0
    o['parts'] = parts
    return o
out = []
for i in ids:
    A = load(labels[0], i)
    row = {'id': i}
    for l in labels:
        X = load(l, i) if l != labels[0] else A
        c, k = X['case'], X['chk']; st = c.get('stats') or {}
        row[l] = {'class': c.get('class'), 'issues': c.get('issues'), 'issues_info': [x for x in (c.get('issues_info') or []) if 'km_shift' in x or 'far' in x],
                  'standins': [(s.get('type'), s.get('count')) for s in c.get('standins') or []], 'levels': st.get('levels'),
                  'tags': {t: n for t, n in (st.get('tags') or {}).items() if t in ('far-origin', 'L1-triangulated', 'L2-alt-source', 'L4-surface', 'open-surface', 'open_in_source', 'instanced')},
                  'out_mb': round((st.get('out_bytes') or 0) / 1048576, 2), 'roots': k.get('roots'), 'transferred': k.get('transferred'), 'empty_roots': k.get('empty_roots'),
                  'solids': k.get('solids'), 'valid': k.get('valid'), 'invalid': k.get('invalid'), 'shells': k.get('shells'), 'nonpos': k.get('nonpos_vol'),
                  'bbox': k.get('bbox'), 'far_check': k.get('far_check'), 'far_points': k.get('far_points'), 'mapped': (k.get('markers') or {}).get('MAPPED_ITEM'),
                  'products': len(X['parts']), 'cov_all': c.get('coverage_all'), 'cov_mem': c.get('coverage_members'), 'sec': c.get('sec'), 'rss_mb': c.get('peak_tree_rss_mb'),
                  'vol_out_tol': (c.get('join') or {}).get('parts_outside_volume_tolerance') if isinstance(c.get('join'), dict) else None}
        if l != labels[0]:
            pa, pb = A['parts'], X['parts']
            miss = [p for p in pa if p not in pb]; extra = [p for p in pb if p not in pa]
            dv = []; dsol = 0; dvalid = 0
            for p in pa:
                if p in pb:
                    a_, b_ = pa[p], pb[p]
                    if a_['solids'] != b_['solids']: dsol += 1
                    if (a_['valid'] == a_['solids']) != (b_['valid'] == b_['solids']): dvalid += 1
                    va, vb = a_['vol'], b_['vol']
                    if va > 0 and vb > 0 and abs(va - vb) / max(va, vb) > 1e-3:
                        dv.append((p, round(va, 1), round(vb, 1), round(vb / va, 5)))
            row[l]['vs_' + labels[0]] = {'parts_missing': len(miss), 'parts_extra': len(extra), 'parts_solid_count_diff': dsol, 'parts_valid_flag_diff': dvalid,
                                         'parts_vol_diff_gt_1e-3': len(dv), 'vol_diff_examples': sorted(dv, key=lambda t: -abs(math.log(t[3])))[:8],
                                         'missing_examples': miss[:5], 'extra_examples': extra[:5],
                                         'total_vol_ratio': round(sum(x['vol'] for x in pb.values()) / max(1e-9, sum(x['vol'] for x in pa.values())), 6) if pa else None}
    out.append(row)
json.dump(out, open('/work/agentwork/ifc-verification-residue-review/cmp_%s.json' % '_'.join(labels), 'w'), indent=1, default=str)
for row in out:
    print(row['id'][:12], ' | '.join('%s c%s %s inv%s sol%s/%s prod%s %sMB' % (l, row[l]['class'], row[l]['levels'], row[l]['invalid'], row[l]['valid'], row[l]['solids'], row[l]['products'], row[l]['out_mb']) for l in labels))
    for l in labels[1:]:
        v = row[l]['vs_' + labels[0]]
        if any(v[k] for k in ('parts_missing', 'parts_extra', 'parts_solid_count_diff', 'parts_valid_flag_diff', 'parts_vol_diff_gt_1e-3')):
            print('   ', l, 'vs', labels[0], json.dumps(v, default=str)[:700])
