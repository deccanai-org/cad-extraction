#!/usr/bin/env python3
"""Find published STEP outputs that OpenCASCADE cannot read because of the old name encoding ('''' inside a string,
from names with two consecutive apostrophes, e.g. Revit feet-inch 8''). Only outputs that were NOT read back
(validate skipped, > RB_MAX) can be affected: a read-back would have failed.
usage: quote_scan.py PIPE [--codes a,b] [--write]   -> _control/conv/<pipe>/_scan/quote_scan.json (+ redo_ids.json with --write)"""
import sys, json, re, argparse, time
from concurrent.futures import ThreadPoolExecutor
import boto3
from botocore.config import Config
B = 'annotationprod'; Z4 = 'cad-disk-extract/zentitude-data-4'
s3 = boto3.client('s3', region_name='ap-south-1', config=Config(max_pool_connections=64, retries={'max_attempts': 8, 'mode': 'adaptive'}))
BAD = re.compile(rb"''''")


def results(pipe):
    out = []
    for pg in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=f'{Z4}/_state/conv/{pipe}/results/'):
        out += [o['Key'] for o in pg.get('Contents', [])]
    return out


def load(k):
    try:
        return json.loads(s3.get_object(Bucket=B, Key=k)['Body'].read())
    except Exception:
        return None


_PC = {}


def pclient():
    import os
    if _PC.get('pid') != os.getpid():
        _PC['pid'] = os.getpid(); _PC['c'] = boto3.client('s3', region_name='ap-south-1', config=Config(retries={'max_attempts': 8, 'mode': 'adaptive'}))
    return _PC['c']


def scan(key):
    """count '''' in a STEP object (streamed; runs in a worker process)"""
    n = 0; tail = b''
    body = pclient().get_object(Bucket=B, Key=key)['Body']
    for chunk in body.iter_chunks(1 << 24):
        buf = tail + chunk; cut = buf.rfind(b'\n')
        if cut < 0:
            tail = buf; continue
        tail = buf[cut + 1:]
        for m in BAD.finditer(buf, 0, cut):
            n += 1
    return n


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('pipe'); ap.add_argument('--codes', default=''); ap.add_argument('--write', action='store_true')
    a = ap.parse_args(); t0 = time.time()
    keys = results(a.pipe)
    with ThreadPoolExecutor(48) as ex:
        rs = [r for r in ex.map(load, keys) if r]
    codes = set(filter(None, a.codes.split(',')))
    cand = []
    for r in rs:
        if r.get('status') != 'ok' or (codes and r.get('code') not in codes):
            continue
        v = r.get('validate') or r.get('readback') or {}
        if v.get('read_status') == 'ok':
            continue                              # read back fine
        key = (r.get('step') or {}).get('key') or r.get('out_key')
        if key:
            cand.append((r['id'], key, (r.get('step') or {}).get('bytes') or r.get('out_bytes')))
    print(f'{len(rs)} results, {len(cand)} published without read-back', flush=True)
    hits = {}
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor(int(__import__('os').environ.get('QS_PROCS', '12'))) as ex:
        for (jid, key, nb), n in zip(cand, ex.map(scan, [c[1] for c in cand], chunksize=1)):
            if n:
                hits[jid] = n
    rep = {'pipe': a.pipe, 'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'results': len(rs), 'scanned': len(cand),
           'scanned_bytes': sum(c[2] or 0 for c in cand), 'affected': len(hits), 'ids': hits, 'sec': round(time.time() - t0)}
    s3.put_object(Bucket=B, Key=f'{Z4}/_control/conv/{a.pipe}/_scan/quote_scan.json', Body=json.dumps(rep, indent=1).encode())
    print(json.dumps({k: v for k, v in rep.items() if k != 'ids'}), flush=True)
    if a.write and hits:
        try:
            d = json.loads(s3.get_object(Bucket=B, Key=f'{Z4}/_control/conv/{a.pipe}/redo_ids.json')['Body'].read())
            if not isinstance(d, dict): d = {}
        except Exception:
            d = {}
        prev = set(d.get('ids') or [])
        new = sorted(prev | set(hits))
        if len(new) != len(prev):
            doc = dict(d); doc.update({'codes': sorted(codes), 'ids': new, 'why': "published without OCC read-back; contains '''' (old name encoding) that OpenCASCADE cannot read", 'updated': rep['at']})
            s3.put_object(Bucket=B, Key=f'{Z4}/_control/conv/{a.pipe}/redo_ids.json', Body=json.dumps(doc).encode(), ContentType='application/json')
            print('redo_ids.json', len(prev), '->', len(new), flush=True)


if __name__ == '__main__':
    main()
