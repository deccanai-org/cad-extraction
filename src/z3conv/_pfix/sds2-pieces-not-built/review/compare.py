#!/usr/bin/env python3
"""compare.py ABDIR OUT.json : per job v553 vs v553p (manifest, pieces.csv rows, skipped.csv rows)"""
import sys, os, json, csv, glob, collections
ab, outp = sys.argv[1], sys.argv[2]
def load(v, n):
    d = os.path.join(ab, v, n); r = {}
    try: r['rc'] = open(os.path.join(d, 'rc.txt')).read().strip()
    except Exception: r['rc'] = None
    m = glob.glob(os.path.join(d, '*_manifest.json'))
    r['man'] = json.load(open(m[0])) if m else None
    rows = {}
    for f in glob.glob(os.path.join(d, '*_pieces.csv')):
        for x in csv.DictReader(open(f)):
            rows[(x['member'], x['piece'], x['inst'], x.get('name', ''))] = (x.get('builder', ''), x.get('standin', '')[:60])
    r['rows'] = rows
    sk = {}
    for f in glob.glob(os.path.join(d, '*_skipped.csv')):
        for x in csv.DictReader(open(f)):
            sk[(x['member'], x['piece'], x['inst'], x.get('name', ''))] = x.get('reason', '')
    r['sk'] = sk
    import re as _re
    r['totvol'] = None
    for f in glob.glob(os.path.join(d, '*_stage2.log')):
        for line in open(f, errors='replace'):
            m_ = _re.search(r'total volume: ([0-9.]+) in3', line)
            if m_: r['totvol'] = float(m_.group(1))
    return r
def summ(m):
    if not m: return None
    c = m.get('counts', {}); rb = m.get('readback', {}); sk = m.get('skipped', {}); wc = m.get('weight_check', {}) or {}
    return dict(cls=m.get('class'), corpus=m.get('corpus'), reasons=m.get('class_reasons', [])[:4],
                counts={k: c.get(k) for k in ('placed_pieces', 'pieces_written', 'pieces_exact', 'pieces_approx', 'reference_placements', 'reference_parts',
                                              'reference_open_shells', 'reference_face_sets', 'reference_skipped', 'pieces_exact_without_table_data', 'rolled_sds2_weight_outliers') if k in c},
                skipped=dict(total=sk.get('total'), by_reason=sk.get('by_reason'), source_absent=sk.get('source_absent'), needed=list((sk.get('needed') or {}).keys())),
                readback={k: rb.get(k) for k in ('top_level_shapes', 'solids', 'valid', 'invalid', 'surfaces', 'load_errors')},
                ratio=wc.get('ratio'), standins=(m.get('standins') or {}).get('by_type'))
res = {}
names = sorted(set(os.listdir(os.path.join(ab, 'v553'))) | set(os.listdir(os.path.join(ab, 'v553p'))))
for n in names:
    a, b = load('v553', n), load('v553p', n)
    tr = collections.Counter(); lost = []; new = []
    for k, va in a['rows'].items():
        vb = b['rows'].get(k)
        if vb is None:
            lost.append((k, va, b['sk'].get(k)))
        elif va[0] != vb[0]:
            tr[f'{k[3][:14]}: {va[0]} -> {vb[0]}'] += 1
    for k, vb in b['rows'].items():
        if k not in a['rows']:
            new.append((k, vb, a['sk'].get(k)))
    sktr = collections.Counter()
    for k, ra in a['sk'].items():
        rb_ = b['sk'].get(k)
        if rb_ != ra: sktr[f'{k[3][:14]}: {ra} -> {rb_ or ("written:" + str(b["rows"].get(k, ("?",))[0]))}'] += 1
    for k, rb_ in b['sk'].items():
        if k not in a['sk']: sktr[f'{k[3][:14]}: {("written:" + str(a["rows"].get(k, ("?",))[0]))} -> {rb_}'] += 1
    mb = b['man'] or {}
    det = collections.Counter()
    for d in ((mb.get('skipped') or {}).get('source_detail') or []):
        import re
        z = re.search(r'in a (\d+)-byte file', d.get('detail', ''))
        det[f"{d['reason']} | {d['name'][:16]} | {z.group(1) + 'B' if z else d.get('detail','')[:70]}"] += 1
    res[n] = dict(rc=[a['rc'], b['rc']], totvol=[a['totvol'], b['totvol']], a=summ(a['man']), b=summ(b['man']), n_rows=[len(a['rows']), len(b['rows'])],
                  builder_changes=dict(tr.most_common(40)), lost_rows=len(lost), lost_examples=[str(x) for x in lost[:15]],
                  new_rows=len(new), new_by=dict(collections.Counter(f"{x[0][3][:14]}:{x[1][0]} (was {x[2]})" for x in new).most_common(25)),
                  skip_changes=dict(sktr.most_common(40)), source_detail=dict(det.most_common(30)))
json.dump(res, open(outp, 'w'), indent=1, default=str)
for n, r in res.items():
    a, b = r['a'] or {}, r['b'] or {}
    print(f"{n[:40]:40s} rc {r['rc']} cls {a.get('cls')}{a.get('corpus')}->{b.get('cls')}{b.get('corpus')} rows {r['n_rows']} lost {r['lost_rows']} new {r['new_rows']} "
          f"skip {(a.get('skipped') or {}).get('total')}->{(b.get('skipped') or {}).get('total')} rb {(a.get('readback') or {}).get('valid')}/{(a.get('readback') or {}).get('solids')}->{(b.get('readback') or {}).get('valid')}/{(b.get('readback') or {}).get('solids')} "
          f"ratio {a.get('ratio')}->{b.get('ratio')} vol {r['totvol']}")
