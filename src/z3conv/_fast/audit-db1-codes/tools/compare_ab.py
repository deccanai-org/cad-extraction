"""bolts vs nobolts (same code f): parts lost / gained, per model"""
import json, gzip, glob, os, collections
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
rows = []
tot = collections.Counter()
for p in sorted(glob.glob(f'{ROOT}/runs/f_bolts/*.json')):
    i = os.path.basename(p)[:-5]
    a = json.load(open(p)); b = json.load(open(f'{ROOT}/runs/f_nobolts/{i}.json'))
    pa = {r[0]: r for r in json.load(gzip.open(p + '.parts.json.gz', 'rt'))}
    pb = {r[0]: r for r in json.load(gzip.open(f'{ROOT}/runs/f_nobolts/{i}.json.parts.json.gz', 'rt'))}
    wa = {k for k, r in pa.items() if r[3] == 'written'}; wb = {k for k, r in pb.items() if r[3] == 'written'}
    nonbolt_lost = [pb[k] for k in wb - wa if pb[k][4] != 'bolt_group_excluded']
    lost_any = sorted(wb - wa); gained = wa - wb
    gained_kinds = collections.Counter(pa[k][4] for k in gained)
    status_change = [(k, pb[k][4], pa[k][4]) for k in set(pa) & set(pb) if pa[k][3] != pb[k][3] or (pa[k][4] != pb[k][4] and pb[k][4] != 'bolt_group_excluded')]
    rec = dict(id=i, written_bolts=a.get('written'), written_nobolts=b.get('written'), decoded_bolts=len(pa), decoded_nobolts=len(pb),
               lost=len(lost_any), nonbolt_lost=len(nonbolt_lost), gained=dict(gained_kinds), status_changes=status_change[:5],
               cuts_applied=(a.get('cuts_applied'), b.get('cuts_applied')),
               skipped_bolts=a.get('skipped'), skipped_nobolts=b.get('skipped'))
    rows.append(rec)
    tot['lost'] += len(lost_any); tot['nonbolt_lost'] += len(nonbolt_lost); tot['models'] += 1
    for k, v in gained_kinds.items(): tot['gained_' + k] += v
json.dump(rows, open(f'{ROOT}/report_ab_parts.json', 'w'), indent=1, default=str)
print(dict(tot))
for r in rows:
    if r['lost'] or r['status_changes'] or r['decoded_bolts'] != r['decoded_nobolts']:
        print(r['id'][:12], r)
