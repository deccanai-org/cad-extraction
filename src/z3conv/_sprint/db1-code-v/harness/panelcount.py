import json, gzip, re, collections, concurrent.futures as cf, boto3
s3 = boto3.client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'
S = json.load(open('/opt/db1v/panelsample.json'))
R = re.compile(r'^\s*(\d+(?:\.\d+)?)\s*[\*X]\s*(\d+(?:\.\d+)?)\s*\[approx: panel')
def one(r):
    try:
        b = s3.get_object(Bucket=B, Key=r['dp'] + '.src_parts.jsonl.gz')['Body'].read()
    except Exception as e:
        return r, None
    c = collections.Counter(); studs = collections.Counter()
    for l in gzip.decompress(b).decode('utf-8', 'replace').splitlines():
        try: n = json.loads(l).get('name') or ''
        except Exception: continue
        m = R.match(n)
        if m: c['square' if abs(float(m.group(1)) - float(m.group(2))) < 1e-9 else 'nonsquare'] += 1
        if 'shank only' in n: studs[n.split(' [')[0]] += 1
    return r, (dict(c), dict(studs.most_common(8)))
out = []
with cf.ThreadPoolExecutor(16) as ex:
    for r, res in ex.map(one, S): out.append(dict(r, res=res))
json.dump(out, open('/opt/db1v/panelsample_out.json', 'w'))
tot = collections.Counter(); mod = collections.Counter(); st = collections.Counter()
for o in out:
    if not o['res']: mod['no_detail'] += 1; continue
    c, sd = o['res']
    for k, v in c.items(): tot[k] += v
    if 'section_parametric_panel' in o['tags']:
        mod['panel_models'] += 1
        if c.get('square') and not c.get('nonsquare'): mod['panel_all_square'] += 1
        if not c: mod['panel_tag_but_no_named_parts'] += 1
    for k, v in sd.items(): st[k] += v
print(dict(tot), dict(mod)); print(st.most_common(25))
