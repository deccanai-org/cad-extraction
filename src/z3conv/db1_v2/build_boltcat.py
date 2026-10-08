"""Aggregate the IFC bolt-assembly harvest (box boltcat.jsonl) into Tekla's own head / nut / washer dimensions per
(bolt standard, nominal diameter) -> tekla_bolt_assemblies.json. Item roles from the mapped bolt representation (local +y
= bolt axis, shank = circle d over L): head = the non-hole solid ending at the shank start, washers = thin circles wider than
the hole, nut = polygon after the grip; hole cylinders (diameter = pset hole diameter) are skipped."""
import json, collections, sys, statistics
R = [json.loads(l) for l in open(sys.argv[1])]
agg = collections.defaultdict(lambda: collections.defaultdict(collections.Counter)); files = collections.defaultdict(set); cnt = collections.Counter()
for r in R:
    for g in r.get('groups') or []:
        std = (g['key'][0] or '').strip(); ex = g.get('ex') or {}; it = g.get('items') or []
        d = ex.get('d'); L = ex.get('L'); ps = ex.get('pset') or {}
        if not std or not d or not it: continue
        hole = ps.get('Bolt hole diameter')
        sh = [x for x in it if x.get('kind') == 'circle' and abs(x['dia'] - d) < 0.05 and L and abs(x['depth'] - L) < 0.5]
        if not sh: continue
        sh = sh[0]; y0 = sh['pos'][1]; y1 = y0 + sh['depth']
        key = (std, round(d, 3))
        cnt[key] += g.get('n', 1); files[key].add(r['key'])
        for x in it:
            if x is sh or 'pos' not in x: continue
            y = x['pos'][1]; ye = y + x['depth']
            isholecyl = x.get('kind') == 'circle' and hole and abs(x['dia'] - hole) < 0.2
            if isholecyl: continue
            if abs(ye - y0) < 0.05 and y < y0:            # ends at the shank start: head
                agg[key]['head'][(x.get('kind'), x.get('af') or x.get('dia'), round(x['depth'], 3))] += 1
            elif x.get('kind') == 'circle' and x['dia'] > d * 1.3 and x['depth'] < 0.5 * d:
                agg[key]['washer'][(round(x['dia'], 3), round(x['depth'], 3))] += 1
            elif x.get('kind', '').startswith('poly') and y >= y0:
                agg[key]['nut'][(x.get('kind'), x.get('af'), round(x['depth'], 3))] += 1
out = {}
for key, roles in agg.items():
    std, d = key
    e = {'standard': std, 'd': d, 'groups': cnt[key], 'files': len(files[key]), 'src': sorted(files[key])[:3]}
    for role, c in roles.items():
        (v, n) = c.most_common(1)[0]; tot = sum(c.values())
        e[role] = {'value': list(v), 'share': round(n / tot, 3), 'samples': tot}
    out[f'{std}|{d:g}'] = e
json.dump(out, open(sys.argv[2], 'w'), indent=1)
print('entries', len(out), 'with head', sum(1 for e in out.values() if 'head' in e), 'nut', sum(1 for e in out.values() if 'nut' in e), 'washer', sum(1 for e in out.values() if 'washer' in e))
for k in sorted(out, key=lambda k: -out[k]['groups'])[:12]:
    e = out[k]; print(k, e['groups'], e['files'], {r: (e[r]['value'], e[r]['share']) for r in ('head', 'nut', 'washer') if r in e})
