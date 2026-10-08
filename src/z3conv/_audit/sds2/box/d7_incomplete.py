#!/usr/bin/env python3
"""All SDS2 contents the scan marked complete_layout=False, plus unknown / unreadable versions: which canonical files are
missing, member / piece file counts, loose-folder splits (a sibling content holding the missing main/ or mem/ part), and
other copies of the same job root that are complete. Read-only; writes agentwork/audit-sds2-pipeline/diag/d7_incomplete.json"""
import os, json, gzip, re, collections
import boto3
from botocore.config import Config
from concurrent.futures import ThreadPoolExecutor
B = 'bim-proprietary-data'; ST = 'cad-disk-extract/zenitude-data-3/_state/conv'
OUTP = 'cad-disk-extract/zenitude-data-3/_state/agentwork/audit-sds2-pipeline/diag'
s3 = boto3.client('s3', region_name='ap-south-1', config=Config(max_pool_connections=32, retries={'max_attempts': 20, 'mode': 'standard'}))


def getj(k):
    b = s3.get_object(Bucket=B, Key=k)['Body'].read()
    if b[:2] == b'\x1f\x8b':
        b = gzip.decompress(b)
    try:
        return json.loads(b)
    except Exception:
        return [json.loads(l) for l in b.decode().splitlines() if l.strip()]


contents = getj(f'{ST}/scan/contents_sds2.jsonl.gz')
V = getj(f'{ST}/scan/sds2_versions.json')
index = {r['id']: r for r in getj(f'{ST}/index.jsonl.gz') if r.get('pipeline') == 'sds2'}
by = {c['id']: c for c in contents}


def jobkey(p):
    left, right = (p.split(' :: ', 1) + [''])[:2] if ' :: ' in p else (p, '')
    m = re.match(r'(.*)/(main|mem|subm)/$', left)
    if m and right:
        return right.rstrip('/')
    return (left + ' :: ' + right).rstrip('/') if right else left.rstrip('/')


def leaf(p):
    return p.split(' :: ')[-1].rstrip('/').split('/')[-1].lower()


grp = collections.defaultdict(set); names = collections.defaultdict(set)
for c in contents:
    for p in c['paths']:
        grp[jobkey(p)].add(c['id']); names[leaf(p)].add(c['id'])
sel = [c for c in contents if not c.get('complete_layout', True) or V.get(c['id']) in (None, 'unreadable', 'error')]


def one(c):
    try:
        fl = getj(c['files_key'])
    except Exception as e:
        return {'id': c['id'], 'error': str(e)}
    ps = {f['p'].replace('\\', '/').lower(): f['size'] for f in fl}
    sib = set().union(*[grp[jobkey(p)] for p in c['paths']]) - {c['id']}
    same = set().union(*[names[leaf(p)] for p in c['paths']]) - {c['id']} - sib
    js = None
    if 'main/jsetup' in ps and V.get(c['id']) in ('unreadable', 'error'):
        k = next(f['key'] for f in fl if f['p'].replace('\\', '/').lower() == 'main/jsetup')
        js = s3.get_object(Bucket=B, Key=k, Range='bytes=0-95')['Body'].read().decode('latin-1')
    return {'id': c['id'], 'version': V.get(c['id']), 'complete_layout': c.get('complete_layout'), 'path': c['paths'][0][-170:],
            'n_paths': c['n_paths'], 'files': len(ps), 'bytes': c.get('model_bytes'),
            'has': {k: k in ps for k in ('main/jsetup', 'main/job_mtrl', 'mem/mem_idx', 'subm/subm_idx')},
            'mem_member_files': sum(1 for p in ps if re.match(r'^mem/\d+$', p)), 'subm_piece_files': sum(1 for p in ps if re.match(r'^subm/\d+$', p)),
            'top': dict(collections.Counter(p.split('/')[0] for p in ps).most_common(6)),
            'split_siblings': [{'id': s, 'version': V.get(s), 'complete': by[s].get('complete_layout'), 'files': by[s].get('n_model_files'),
                                'class': (index.get(s) or {}).get('class')} for s in sorted(sib)],
            'same_name_contents': [{'id': s, 'version': V.get(s), 'complete': by[s].get('complete_layout'), 'class': (index.get(s) or {}).get('class')}
                                   for s in sorted(same)][:10],
            'jsetup_head': js, 'class': (index.get(c['id']) or {}).get('class'), 'status': (index.get(c['id']) or {}).get('status')}


with ThreadPoolExecutor(16) as ex:
    rows = list(ex.map(one, sel))
summ = {'selected': len(rows),
        'incomplete_layout': sum(1 for r in rows if r.get('complete_layout') is False),
        'unknown_or_unreadable_version': sum(1 for r in rows if r.get('version') in (None, 'unreadable', 'error')),
        'split_loose_folder (sibling holds the other part)': sum(1 for r in rows if r.get('split_siblings')),
        'missing': dict(collections.Counter(','.join(k for k, v in (r.get('has') or {}).items() if not v) or 'none' for r in rows)),
        'with_member_files_and_piece_files': sum(1 for r in rows if r.get('mem_member_files', 0) > 0 and r.get('subm_piece_files', 0) > 0),
        'no_member_files': sum(1 for r in rows if r.get('mem_member_files', 0) == 0),
        'has_complete_same_name_copy': sum(1 for r in rows if any(x['complete'] for x in r.get('same_name_contents') or []))}
json.dump({'summary': summ, 'rows': rows}, open('/work/agentwork/audit-sds2-pipeline/diag/d7_incomplete.json', 'w'), indent=1)
s3.upload_file('/work/agentwork/audit-sds2-pipeline/diag/d7_incomplete.json', B, f'{OUTP}/d7_incomplete.json')
print(json.dumps(summ, indent=1))
