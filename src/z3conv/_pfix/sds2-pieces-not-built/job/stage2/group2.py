#!/usr/bin/env python3
"""group2.py ROWS.json OUTDIR -> fetch _skipped.csv (+ manifest for v5.x) of every live 'sds2 pieces not built' model
(v4 and v5.x) and group the skipped placements by reason x name family x kind x converter label."""
import sys, os, json, csv, io, re, collections, concurrent.futures as cf
import boto3
B = 'bim-proprietary-data'
s3 = boto3.client('s3', region_name='ap-south-1')
rows = json.load(open(sys.argv[1])); outd = sys.argv[2]; os.makedirs(outd, exist_ok=True)

def fam(name):
    m = re.match(r'[A-Za-z#]+', (name or '').strip())
    return m.group(0) if m else (name or '?')[:6]

def one(r):
    base = r['step_key'][:-len('.step')]
    res = dict(id=r['id'], conv=r['conv'], version=r['version'], only=r['only'], cls=r['cls'], corpus=r['corpus'],
               job=os.path.basename(base)[:-len('_stage2')], base=base)
    try:
        b = s3.get_object(Bucket=B, Key=base + '_skipped.csv')['Body'].read().decode('utf-8', 'replace')
        res['skipped'] = list(csv.DictReader(io.StringIO(b)))
    except Exception as e:
        res['skipped_err'] = f'{type(e).__name__}: {e}'[:200]; res['skipped'] = []
    if r['conv'] != 'v4':
        try:
            m = json.loads(s3.get_object(Bucket=B, Key=base + '_manifest.json')['Body'].read())
            res['counts'] = m.get('counts'); res['class_reasons'] = m.get('class_reasons')
            res['skipped_m'] = m.get('skipped')
        except Exception as e:
            res['manifest_err'] = f'{type(e).__name__}: {e}'[:200]
    return res

with cf.ThreadPoolExecutor(16) as ex:
    got = list(ex.map(one, rows))
G = collections.defaultdict(lambda: dict(placements=0, pieces=set(), models=set(), lift=set(), convs=collections.Counter(), examples=[]))
per_model = []
for g in got:
    pm = collections.Counter(); seen_fam = set()
    for s in g['skipped']:
        reason = s.get('reason') or '?'
        pm[reason] += 1
        for key in [(reason,), (reason, 'fam', fam(s.get('name'))), (reason, 'kind', s.get('kind')),
                    (reason, 'conv', 'v4' if g['conv'] == 'v4' else 'v5x'),
                    (reason, 'fam+kind', f"{fam(s.get('name'))}|{s.get('kind')}")]:
            e = G[key]; e['placements'] += 1; e['pieces'].add((g['id'], s.get('piece'))); e['models'].add(g['id'])
            if g['only']: e['lift'].add(g['id'])
            if g['id'] not in {x[0] for x in e['examples']} and len(e['examples']) < 15:
                e['examples'].append((g['id'], g['job'], g['conv'], g['version'], s.get('piece'), s.get('name'), s.get('kind'), s.get('member_type')))
            if (g['id'], key) not in seen_fam:
                e['convs'][g['conv']] += 1; seen_fam.add((g['id'], key))
    per_model.append(dict(id=g['id'], job=g['job'], conv=g['conv'], version=g['version'], only=g['only'], cls=g['cls'], corpus=g['corpus'],
                          skipped=dict(pm), counts=g.get('counts'), class_reasons=g.get('class_reasons'), skipped_m=g.get('skipped_m'),
                          err=g.get('skipped_err') or g.get('manifest_err'), base=g['base'],
                          pieces=sorted({(s.get('piece'), s.get('name'), s.get('kind'), s.get('reason')) for s in g['skipped']})[:400]))
summ = []
for k, e in G.items():
    summ.append(dict(key=list(k), placements=e['placements'], pieces=len(e['pieces']), models=len(e['models']), lift=len(e['lift']),
                     convs=dict(e['convs']), examples=e['examples']))
summ.sort(key=lambda x: (len(x['key']), x['key'][0], -x['models'], -x['placements']))
json.dump(summ, open(os.path.join(outd, 'groups.json'), 'w'), indent=0)
json.dump(per_model, open(os.path.join(outd, 'per_model.json'), 'w'), indent=0)
print('models', len(got), 'errors', sum(1 for g in got if g.get('skipped_err') or g.get('manifest_err')))
for x in summ:
    if len(x['key']) == 1 or (x['key'][1] in ('fam', 'kind', 'conv', 'fam+kind') and x['models'] >= 3):
        print(x['models'], x['lift'], x['pieces'], x['placements'], x['key'], x['convs'])
