#!/usr/bin/env python3
"""Summarise the data-3 conversion index for the final report (read-only, bim profile)."""
import boto3, json, gzip, collections
s3 = boto3.Session(profile_name='bim').client('s3', region_name='ap-south-1')
B = 'bim-proprietary-data'; ST = 'cad-disk-extract/zenitude-data-3/_state/conv'
st = json.loads(s3.get_object(Bucket=B, Key='cad-disk-extract/zenitude-data-3/_state/conv_status.json')['Body'].read())
summ = json.loads(s3.get_object(Bucket=B, Key=f'{ST}/index_summary.json')['Body'].read())
rows = [json.loads(l) for l in gzip.decompress(s3.get_object(Bucket=B, Key=f'{ST}/index.jsonl.gz')['Body'].read()).decode().splitlines() if l.strip()]
print('updated', st['updated'], 'final', st.get('final'), 'grading', st.get('grading', '')[:20])
for p in ('ifc', 'db1', 'sds2'):
    rs = [r for r in rows if r['pipeline'] == p]
    cls = collections.Counter(str(r['class']) for r in rs)
    corp = collections.Counter(f"{r['class']}{r.get('corpus') or ''}" for r in rs if r['class'])
    reu = collections.Counter(r['reuse_from'] for r in rs if r['reused'])
    sup = sum(1 for r in rs if r.get('supersedes'))
    print(f"\n== {p}: models {len(rs)}  classes {dict(cls)}  corpus {dict(corp)}")
    print(f"   reused {sum(reu.values())} {dict(reu)}  superseded-by-fresh {sup}  new STEP {sum(1 for r in rs if not r['reused'] and r.get('step_key'))}")
    print('   class3 reasons', dict(collections.Counter(x.split(' (')[0].split(':')[0] for r in rs if r['class'] == 3 for x in r['reasons']).most_common(8)))
    print('   class2 issues ', dict(collections.Counter(x.split(':')[0].split(' (')[0] for r in rs if r['class'] == 2 for x in r['issues']).most_common(8)))
    print('   stand-ins     ', dict(collections.Counter(s['type'] for r in rs if r['class'] == 2 for s in r['standins']).most_common(8)))
print('\nfix plan top:')
for x in st.get('fix_plan_top', [])[:10]:
    print('  ', x['models'], 'lift', x['lift_to_class1_if_only_fix'], x['key'])
print('\nhistory:')
for h in st.get('history', []):
    print('  ', h['pipeline'], h['converter'], 'targeted', h['targeted'], 'before', h['before'], 'after', h.get('after'), 'done', h.get('done'))
print('\nfleet', st.get('fleet'))
