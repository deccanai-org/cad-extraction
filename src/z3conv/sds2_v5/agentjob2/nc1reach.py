"""NC1 opt-in reach: for each recall-paired data-3 job with NC1 parts, how many NC1 main-member parts (with holes) pass
the strict match (order == job name, piece mark in the job's pcm_list, ...). Output: nc1reach.jsonl"""
import sys, os, json, gzip, re, collections, traceback
from concurrent.futures import ThreadPoolExecutor
import boto3
sys.path.insert(0, '/work/agentwork/sds2-recall-nc1')
import nc1_holes_check as N
s3 = boto3.client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'
NC1C = '/work/agentwork/sds2-recall-nc1/nc1cache'
pairs = json.load(open('/work/agentwork/sds2-recall-nc1/inv/pairs.json'))
d3 = {j['id']: j for j in json.load(open('/work/agentwork/sds2v54/d3jobs.json'))}
out = open('/work/agentwork/sds2v54/nc1/nc1reach.jsonl', 'w')
norm = lambda s: re.sub(r'[^a-z0-9]', '', (s or '').lower())


def one(item):
    jid, o = item
    r = dict(id=jid, name=o['name'])
    try:
        files = [e for e in o['nc1_files'] if e.get('key')]
        if not files or jid not in d3:
            return None
        mf = json.loads(gzip.decompress(s3.get_object(Bucket=B, Key=d3[jid]['files_key'])['Body'].read()))
        k = next((f['key'] for f in mf if f['p'].replace('\\', '/').lower().endswith('main/jsetup') and f.get('key')), None)
        r['version'] = d3[jid].get('version')
        marks = set()
        if k:
            root = k[:-len('main/jsetup')]
            try:
                b = s3.get_object(Bucket=B, Key=root + 'pcm/pcm_list')['Body'].read()
                n = (len(b) - 256) // 72
                marks = {b[256 + 72 * i: 256 + 72 * i + 40].split(b'\x00')[0].decode('latin-1') for i in range(n)} - {''}
            except Exception:
                r['pcm'] = 'missing'
        r['pcm_marks'] = len(marks); r['pcm_detailed'] = sum(1 for m in marks if '_' not in m)
        c = collections.Counter(); seen = set()
        for e in files:
            if e['sha256'] in seen: continue
            seen.add(e['sha256'])
            p = os.path.join(NC1C, e['sha256'][:2], e['sha256'])
            if not os.path.exists(p): c['not_cached'] += 1; continue
            part = N.parse_nc1(open(p, 'rb').read().decode('latin-1'), e['path'])
            main = part['code'] in ('I', 'U', 'L', 'RO', 'RU', 'M', 'T', 'C')
            if not main or not part['holes']: continue
            c['main_parts_with_holes'] += 1; c['main_holes'] += len(part['holes'])
            okj = norm(part.get('order')) == norm(o['name'])
            okm = part.get('mark') in marks
            c['order_eq'] += okj; c['mark_in_pcm'] += okm
            if okj and okm:
                c['strict_parts'] += 1; c['strict_holes'] += len(part['holes'])
        r.update(c)
    except Exception:
        r['error'] = traceback.format_exc()[-300:]
    return r


todo = [(j, o) for j, o in pairs.items() if any(e.get('key') for e in o['nc1_files'])]
print('jobs', len(todo), flush=True)
tot = collections.Counter()
with ThreadPoolExecutor(16) as ex:
    for r in ex.map(one, todo):
        if r is None: continue
        out.write(json.dumps(r) + '\n')
        for k in ('main_parts_with_holes', 'main_holes', 'order_eq', 'mark_in_pcm', 'strict_parts', 'strict_holes'):
            tot[k] += r.get(k, 0)
        tot['jobs'] += 1; tot['jobs_strict'] += bool(r.get('strict_parts'))
print(dict(tot), flush=True)
