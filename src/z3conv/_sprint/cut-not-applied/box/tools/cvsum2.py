"""cvsum2.py KIT_A KIT_B : convert-only corpus results per model and per engine (convall/<kit>/<id>/convert.json), incl. cut_stats"""
import os, sys, json, glob, collections
A, B = sys.argv[1], sys.argv[2]
R = {}
for k in (A, B):
    for d in glob.glob(f'convall/{k}/*'):
        i = os.path.basename(d); c = {}; cj = {}
        try: c = json.load(open(f'{d}/convert.json'))
        except Exception: pass
        try: cj = json.load(open(f'{d}/conv.json'))
        except Exception: pass
        R.setdefault(i, {})[k] = (c, cj)
def g(c, *ks):
    for k in ks: c = (c or {}).get(k) if isinstance(c, dict) else None
    return c or 0
E = collections.defaultdict(collections.Counter); rows = []
for i, v in sorted(R.items()):
    if A not in v or B not in v: continue
    (a, aj), (b, bj) = v[A], v[B]
    eng = aj.get('engine') or bj.get('engine')
    sa, sb = a.get('skipped') or {}, b.get('skipped') or {}
    r = dict(id=i, eng=eng, st=(a.get('status'), b.get('status')), written=(a.get('written'), b.get('written')),
             applied=(a.get('cuts_applied'), b.get('cuts_applied')), cutparts=(sa.get('cut_part_excluded', 0), sb.get('cut_part_excluded', 0)),
             unbuilt=(sa.get('cut_body_unbuilt', 0), sb.get('cut_body_unbuilt', 0)), zero=(sa.get('cut_body_zero_thickness', 0), sb.get('cut_body_zero_thickness', 0)),
             sec=(aj.get('sec'), bj.get('sec')), rc=(aj.get('rc'), bj.get('rc')), members=(a.get('members'), b.get('members')),
             cut_stats=(a.get('cut_stats'), b.get('cut_stats')), fittings=(a.get('fittings'), b.get('fittings')),
             attr_salv=g(b, 'layout', 'attr_salvaged'), op_parts=g(b, 'layout', 'cut_operative_parts'), rel=g(b, 'layout', 'relation_type11_by_stride'),
             linked_iso=g(b, 'cut_layout', 'linked_isolated'), holes=(g(a, 'bolt_stats', 'holes_cut'), g(b, 'bolt_stats', 'holes_cut')))
    rows.append(r)
    e = E[eng]; e['models'] += 1
    for k2 in ('written', 'applied', 'cutparts', 'unbuilt', 'members', 'zero', 'holes'):
        e[k2 + '_before'] += r[k2][0] or 0; e[k2 + '_after'] += r[k2][1] or 0
    e['models_with_unbuilt_before'] += (r['unbuilt'][0] or 0) > 0; e['models_with_unbuilt_after'] += (r['unbuilt'][1] or 0) > 0
    e['status_changed'] += r['st'][0] != r['st'][1]
    for k2 in ('unlinked', 'links_to_unwritten_parts'):
        e[k2 + '_after'] += g(r['cut_stats'][1], k2)
for r in rows: print(json.dumps(r))
print('PER ENGINE')
tot = collections.Counter()
for eng, e in sorted(E.items(), key=lambda x: str(x[0])):
    print(eng, dict(e)); tot.update(e)
print('TOTAL', dict(tot))
