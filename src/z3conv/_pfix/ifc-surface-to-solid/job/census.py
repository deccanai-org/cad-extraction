import json, boto3, collections, concurrent.futures, sys, os
s3 = boto3.client('s3', region_name='ap-south-1')
B = 'bim-proprietary-data'
R = 'cad-disk-extract/zenitude-data-3/_state/conv/'
ids = json.load(open('ids.json'))
def get(row):
    pipe, id_, key, size, dp = row
    out = {'pipe': pipe, 'id': id_, 'size': size}
    d = None
    for k in (key + '.parts.json',):
        try:
            d = json.loads(s3.get_object(Bucket=B, Key=k)['Body'].read()); break
        except Exception as e:
            out['err'] = str(e)[:100]
    if d is None:
        return out
    out.pop('err', None)
    out['converter'] = d.get('converter')
    out['nparts'] = len(d['parts'])
    out['bad'] = [p for p in d['parts'] if set(p['tags']) & {'L3', 'L4', 'unverified'}]
    # results json for input key
    try:
        rj = json.loads(s3.get_object(Bucket=B, Key=R + '%s/results/%s.json' % ('ifc' if pipe == 'ifc' else pipe, id_))['Body'].read())
        out['input_key'] = rj.get('input_key')
        st = (rj.get('attempts') or [{}])[-1].get('stats') or {}
        out['verify_L0'] = st.get('verify_L0'); out['repair'] = st.get('repair'); out['prec'] = st.get('prec')
    except Exception as e:
        out['rj_err'] = str(e)[:100]
    return out
res = []
with concurrent.futures.ThreadPoolExecutor(16) as ex:
    for o in ex.map(get, ids):
        res.append(o)
json.dump(res, open('census_out.json', 'w'))
# aggregate
agg = collections.Counter(); hist = collections.Counter(); bycls = collections.Counter(); bysrc = collections.Counter(); tg = collections.Counter()
nf = []
for o in res:
    for p in o.get('bad') or []:
        h = '|'.join(p.get('why') or [])
        hist[h] += 1
        bycls[p['cls']] += 1; bysrc[p['src']] += 1
        for t in p['tags']: tg[t] += 1
        nf.append(p.get('faces') or 0)
summ = {'models': len(res), 'errs': [o for o in res if 'err' in o][:20], 'parts': sum(len(o.get('bad') or []) for o in res),
        'hist': hist.most_common(60), 'cls': bycls.most_common(30), 'src': bysrc.most_common(), 'tags': tg.most_common(40),
        'faces_hist': collections.Counter(min(10**len(str(x)), 10**7) for x in nf).most_common()}
json.dump(summ, open('census_summary.json', 'w'), indent=1)
print(json.dumps(summ)[:6000])
