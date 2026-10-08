import json, glob, sys, collections
G = []
for f in glob.glob(sys.argv[1] + '/*.json'):
    j = json.load(open(f)); ga = j.get('gattr') or {}
    for r in j.get('rows', []):
        if r['pred'] is not True or r['truth'] != ['slot']: continue
        pa = r['palong']; nd = set(r['ncdir'])
        if not (pa > 0.99 or pa < 0.01) or len(nd) != 1: continue
        want = 'True' if pa > 0.99 else 'False'
        G.append(dict(m=f.split('/')[-1][:12], e=j['engine'], g=r['g'], ok=(want in nd), rank=r.get('rank'), n=r['n'], mask=r['mask'], sx=r['sx'], sy=r['sy'],
                      bstr=r.get('bstr'), gx=r.get('gx'), prof=r['prof'], ga=(ga.get(str(r['g'])) or {}).get('i32')))
print(len(G), collections.Counter((x['e'], x['ok']) for x in G))
bad = [x for x in G if not x['ok']]
for x in bad[:40]: print('BAD', x['m'], x['e'], x['g'], x['rank'], x['n'], x['mask'], x['sx'], x['sy'], x['gx'], x['prof'], x['bstr'])
good = [x for x in G if x['ok']]
for x in good[:15]: print('OK ', x['m'], x['e'], x['g'], x['rank'], x['n'], x['mask'], x['sx'], x['sy'], x['gx'], x['prof'], x['bstr'])
# bolt-string field and attr int field separation
def fields(x):
    d = {}
    for i, v in enumerate((x['bstr'] or '').split('/')): d['s%d' % i] = v
    for i, v in enumerate(x['ga'] or []): d['i%d' % (4 * i)] = v
    d['rank'] = x['rank']; d['rankpar'] = (x['rank'] or 0) % 2; d['sxy'] = (x['sx'] > 0, x['sy'] > 0)
    return d
F = collections.defaultdict(lambda: collections.Counter())
for x in G:
    for k, v in fields(x).items(): F[k][(v, x['ok'])] += 1
for k, c in F.items():
    vals = {v for v, _ in c}
    if len(vals) > 30: continue
    sep = all(not (c[(v, True)] and c[(v, False)]) for v in vals)
    if sep and len(vals) > 1: print('SEPARATES', k, dict(c))
for k in ('rank', 'rankpar', 'sxy', 's4', 's5', 's6', 's7', 's8', 's9', 's10'):
    print(k, dict(F[k]))
