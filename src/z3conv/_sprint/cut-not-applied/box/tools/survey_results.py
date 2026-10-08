"""survey_results.py : every DB1 row of the conv index -> its converter result -> cut stats + input key (data/db1_all.json)"""
import json, gzip, boto3, collections, concurrent.futures as cf
s3 = boto3.client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'
R = 'cad-disk-extract/zenitude-data-3/_state/conv'
def getj(k):
    try: return json.loads(s3.get_object(Bucket=B, Key=k)['Body'].read())
    except Exception: return None
rows = [json.loads(l) for l in gzip.open('data/index.jsonl.gz', 'rt')]
db = [r for r in rows if r.get('pipeline') == 'db1']
def one(r):
    jid = r['id']
    res = getj(f'{R}/db1/results/{jid}.json'); src = 'z3'
    g = getj(f'{R}/grade/results/db1-{jid}.json')
    if res is None and g:
        res = g.get('prior_result') or (getj(g['result_key']) if g.get('result_key') else None); src = 'grade:' + str(g.get('reuse_from'))
    res = res or {}
    cv = res.get('convert') or {}
    lay = res.get('layout') or cv.get('layout') or {}
    ik = res.get('input_key') or (g or {}).get('input_key')
    return dict(id=jid, sha256=jid, size=r.get('size'), engine=r.get('engine') or res.get('engine'), cls=r.get('class'), status=r.get('status'),
                issues=r.get('issues'), code=r.get('converter_code') or res.get('code'), src=src, input_key=ik,
                g_input=(g or {}).get('input_key'), redecode=bool((g or {}).get('redecode')),
                cut_layout=cv.get('cut_layout'), cuts_applied=cv.get('cuts_applied'), skipped=cv.get('skipped'),
                cut_relations=lay.get('cut_relations'), written=cv.get('written'), members=cv.get('members'), paths=r.get('paths', [])[:2],
                g_keys=sorted((g or {}).keys())[:60])
with cf.ThreadPoolExecutor(16) as ex:
    out = list(ex.map(one, db))
json.dump(out, open('data/db1_all.json', 'w'), indent=0, default=str)
print('rows', len(out), 'with input_key', sum(1 for o in out if o['input_key']))
print('g keys sample', out[0]['g_keys'])
for o in sorted(out, key=lambda o: str(o['engine'])):
    sk = o['skipped'] or {}
    print(o['id'][:16], o['engine'], o['cls'], (o['code'] or '')[-3:], o['src'][:14], 'size', o['size'], '| cuts', sk.get('cut_part_excluded'), 'unbuilt', sk.get('cut_body_unbuilt'),
          'applied', o['cuts_applied'], 'rel', o['cut_relations'], 'layout', o['cut_layout'], '| key', bool(o['input_key']))
