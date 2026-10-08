#!/usr/bin/env python3
"""SDS/2 job versions at scan time: main/jsetup header ("version 7.331") of every distinct job -> _state/conv/scan/sds2_versions.json"""
import json, gzip, re, boto3
from concurrent.futures import ThreadPoolExecutor
from botocore.config import Config
B = 'bim-proprietary-data'; ST = 'cad-disk-extract/zenitude-data-3/_state/conv'
s3 = boto3.client('s3', region_name='ap-south-1', config=Config(retries={'max_attempts': 40, 'mode': 'standard'}, max_pool_connections=96))
rows = [json.loads(l) for l in gzip.decompress(s3.get_object(Bucket=B, Key=f'{ST}/scan/contents_sds2.jsonl.gz')['Body'].read()).decode().splitlines() if l.strip()]


def one(r):
    try:
        b = s3.get_object(Bucket=B, Key=r['files_key'])['Body'].read()
        fl = json.loads(gzip.decompress(b) if b[:2] == b'\x1f\x8b' else b)
        js = next((f for f in fl if f['p'].lower() == 'main/jsetup'), None)
        if not js or not js.get('key'):
            return r['id'], None
        h = s3.get_object(Bucket=B, Key=js['key'], Range='bytes=0-127')['Body'].read()
        m = re.match(rb'\s*version\s+([0-9.]+)', h)
        return r['id'], (m.group(1).decode() if m else 'unreadable')
    except Exception as e:
        return r['id'], f'error'
out = {}
with ThreadPoolExecutor(64) as ex:
    for i, v in ex.map(one, rows):
        out[i] = v
s3.put_object(Bucket=B, Key=f'{ST}/scan/sds2_versions.json', Body=json.dumps(out).encode(), ContentType='application/json')
import collections
print(len(out), collections.Counter((v or 'none')[:3] for v in out.values()).most_common(20))
