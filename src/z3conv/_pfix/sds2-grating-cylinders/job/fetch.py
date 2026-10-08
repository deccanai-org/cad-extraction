#!/usr/bin/env python3
"""Materialize an SDS/2 job folder from stored objects in bim-proprietary-data (data-3 / data-4 / Disk-1/2 keys) (run in a child process: many small GETs).
usage: fetch.py LIST.json THREADS   LIST = [[key, local_path, size], ...]   -> prints JSON {n, bytes, errors, sec}"""
import sys, os, json, time
from concurrent.futures import ThreadPoolExecutor
import boto3
from botocore.config import Config
s3 = boto3.client('s3', region_name='ap-south-1', config=Config(max_pool_connections=96, retries={'max_attempts': 40, 'mode': 'standard'}))
items = json.load(open(sys.argv[1])); nt = int(sys.argv[2]) if len(sys.argv) > 2 else 48
t0 = time.time(); errs = []


def one(it):
    key, path, size = it
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not key:
        open(path, 'wb').close(); return 0
    for attempt in range(6):
        try:
            if size < (64 << 20):
                body = s3.get_object(Bucket='bim-proprietary-data', Key=key)['Body'].read()
                with open(path, 'wb') as f: f.write(body)
            else:
                s3.download_file('bim-proprietary-data', key, path)
            got = os.path.getsize(path)
            if got != size:
                raise IOError(f'size {got} != {size}')
            return got
        except Exception as e:
            if attempt == 5:
                errs.append([key, f'{type(e).__name__}: {str(e)[:160]}']); return 0
            time.sleep(1 + attempt * 2)


with ThreadPoolExecutor(nt) as ex:
    nb = sum(ex.map(one, items))
print(json.dumps({'n': len(items), 'bytes': nb, 'errors': errs[:20], 'n_errors': len(errs), 'sec': round(time.time() - t0, 1)}))
