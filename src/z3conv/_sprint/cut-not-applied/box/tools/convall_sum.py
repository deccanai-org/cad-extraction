"""convall_sum.py : corpus convert-only results, deployed kit (kit2) vs patched (kitp3): per model and per engine"""
import os, json, glob, collections
R = {}
for k in ('kit2', 'kitp3'):
    for d in glob.glob(f'convall/{k}/*'):
        i = os.path.basename(d); c = {}
        try: c = json.load(open(f'{d}/convert.json'))
        except Exception: pass
        cj = {}
        try: cj = json.load(open(f'{d}/conv.json'))
        except Exception: pass
        R.setdefault(i, {})[k] = (c, cj)
E = collections.defaultdict(collections.Counter); rows = []
def g(c, *ks):
    for k in ks: c = (c or {}).get(k) if isinstance(c, dict) else None
    return c or 0
for i, v in sorted(R.items()):
    if 'kit2' not in v or 'kitp3' not in v: continue
    (a, aj), (b, bj) = v['kit2'], v['kitp3']
    eng = aj.get('engine')
    sa, sb = a.get('skipped') or {}, b.get('skipped') or {}
    r = dict(id=i, eng=eng, st=(a.get('status'), b.get('status')), written=(a.get('written'), b.get('written')),
             applied=(a.get('cuts_applied'), b.get('cuts_applied')), cutparts=(sa.get('cut_part_excluded', 0), sb.get('cut_part_excluded', 0)),
             unbuilt=(sa.get('cut_body_unbuilt', 0), sb.get('cut_body_unbuilt', 0)), sec=(aj.get('sec'), bj.get('sec')),
             attr_salv=g(b, 'layout', 'attr_salvaged'), op_parts=g(b, 'layout', 'cut_operative_parts'), rel=g(b, 'layout', 'relation_type11_by_stride'),
             linked_iso=g(b, 'cut_layout', 'linked_isolated'), members=(a.get('members'), b.get('members')))
    rows.append(r)
    e = E[eng]; e['models'] += 1
    for k2 in ('written', 'applied', 'cutparts', 'unbuilt', 'members'):
        e[k2 + '_before'] += r[k2][0] or 0; e[k2 + '_after'] += r[k2][1] or 0
    e['models_with_unbuilt_before'] += (r['unbuilt'][0] or 0) > 0; e['models_with_unbuilt_after'] += (r['unbuilt'][1] or 0) > 0
    e['status_changed'] += r['st'][0] != r['st'][1]
for r in rows: print(json.dumps(r))
print('PER ENGINE')
tot = collections.Counter()
for eng, e in sorted(E.items(), key=lambda x: str(x[0])):
    print(eng, dict(e)); tot.update(e)
print('TOTAL', dict(tot))
