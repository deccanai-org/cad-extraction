#!/usr/bin/env python3
"""Unlinked reference variant (pp3 / njk / duct-l5): does main/f_guid_map (or any main/ file) hold the placement GUIDs?"""
import json, gzip, re, sys, collections, boto3
from botocore.config import Config
B = 'bim-proprietary-data'; ST = 'cad-disk-extract/zenitude-data-3/_state/conv'
s3 = boto3.client('s3', region_name='ap-south-1', config=Config(max_pool_connections=16, retries={'max_attempts': 10, 'mode': 'standard'}))
def getj(k):
    b = s3.get_object(Bucket=B, Key=k)['Body'].read()
    return json.loads(gzip.decompress(b) if b[:2] == b'\x1f\x8b' else b)
jobs = {j['id']: j for j in getj(f'{ST}/sds2/jobs.json')}
out = {}
for jid in sys.argv[1:]:
    fl = getj(jobs[jid]['files_key'])
    main = {f['p']: (f['size'], f.get('key')) for f in fl if f['p'].lower().startswith('main/')}
    mems = sorted([f for f in fl if re.match(r'(?i)^mem/\d+$', f['p'])], key=lambda f: -f['size'])[:3]
    rx_txt = re.compile(rb'[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}')
    guids_txt = collections.Counter(); sample_bin = []
    for f in mems:
        b = s3.get_object(Bucket=B, Key=f['key'], Range='bytes=0-20000000')['Body'].read()
        for m in rx_txt.finditer(b):
            guids_txt[m.group().lower()] += 1
    res = {'main_files': {p: s for p, (s, k) in main.items()}, 'mem_files_checked': [f['p'] for f in mems],
           'text_guids_in_mem': len(guids_txt), 'sample_guids': list(guids_txt)[:3]}
    hits = {}
    for p, (s, k) in main.items():
        if not k or s == 0 or s > 400_000_000:
            continue
        b = s3.get_object(Bucket=B, Key=k)['Body'].read()
        tg = {m.group().lower() for m in rx_txt.finditer(b)}
        hits[p] = {'text_guids_in_file': len(tg), 'overlap_with_mem_guids': len(tg & set(guids_txt))}
    res['main_guid_hits'] = hits
    out[jid] = res
print(json.dumps(out, indent=1)[:6000])
