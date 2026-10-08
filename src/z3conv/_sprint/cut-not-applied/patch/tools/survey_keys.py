"""survey_keys.py : fill input_key for reused DB1 rows from their disk-1/2 result (grade result -> result_key)"""
import json, boto3, concurrent.futures as cf
s3 = boto3.client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'
R = 'cad-disk-extract/zenitude-data-3/_state/conv'
def getj(k):
    try: return json.loads(s3.get_object(Bucket=B, Key=k)['Body'].read())
    except Exception as e: return None
A = json.load(open('data/db1_all.json'))
def fill(o):
    if o.get('input_key'): return o
    g = getj(f"{R}/grade/results/db1-{o['id']}.json") or {}
    rk = g.get('result_key'); r = getj(rk) if rk else None
    if r is None:
        r = getj(f"cad-disk-extract/_state/db1-v2/results/{o['id']}.json")
    if r:
        o['input_key'] = r.get('input_key') or r.get('key') or r.get('src_key')
        o['rkeys'] = sorted(r.keys())[:40]
        cv = r.get('convert') or {}
        o['cut_layout'] = o.get('cut_layout') or cv.get('cut_layout'); o['cuts_applied'] = o.get('cuts_applied') if o.get('cuts_applied') is not None else cv.get('cuts_applied')
        o['skipped'] = o.get('skipped') or cv.get('skipped'); o['cut_relations'] = o.get('cut_relations') or (r.get('layout') or {}).get('cut_relations')
    o['g_result_key'] = rk
    return o
with cf.ThreadPoolExecutor(16) as ex:
    A = list(ex.map(fill, A))
json.dump(A, open('data/db1_all.json', 'w'), indent=0, default=str)
for o in A:
    if o.get('src', '').startswith('grade') or not o.get('input_key'):
        sk = o.get('skipped') or {}
        print(o['id'][:16], o['engine'], o.get('g_result_key'), '->', (o.get('input_key') or 'NONE')[-100:], '| cuts', sk.get('cut_part_excluded'), 'applied', o.get('cuts_applied'), 'rel', o.get('cut_relations'), o.get('rkeys') if not o.get('input_key') else '')
print('with key', sum(1 for o in A if o.get('input_key')), 'of', len(A))
