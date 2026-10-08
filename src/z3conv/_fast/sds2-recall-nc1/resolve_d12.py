#!/usr/bin/env python3
"""Resolve the NC1 files that data-3 stored as 'prior' (content already extracted from Disk-1 / Disk-2) to stored keys.

Disk-1/2 extraction results list the sha256 of every NC1 file per archive (sha256.nc1):
  cad-disk-extract/_state/results/<id>.json      (GCP run)  files stored under <Disk>/<sanitized archive>-<id[:12]>/...
  cad-disk-extract/_state/ec2-results/<id>.json  (EC2 run)  'uploaded_objects' = every stored key of the archive
For each needed sha: archives whose nc1 list holds it -> that archive's stored .nc1 keys with the same sanitized file
name (and the same size where listed) -> download and verify sha256 (only a verified key is used).
Needed shas = unresolved NC1 files of the paired jobs (pairs.json; --all: every paired job, default: jobs with a STEP).
Output: $W/inv/nc1_keys_d12.json {sha: key}; pairs.json updated in place (key filled, key_from=disk12_verified).
"""
import os, sys, json, re, time, hashlib, collections, pickle
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import boto3
from botocore.config import Config

B = 'bim-proprietary-data'
D12 = 'cad-disk-extract'
D3 = 'cad-disk-extract/zenitude-data-3'
RES = f'{D3}/_state/agentwork/sds2-recall-nc1'
W = os.environ.get('W', '/work/agentwork/sds2-recall-nc1')
INV = os.path.join(W, 'inv'); RD = os.path.join(INV, 'd12results'); os.makedirs(RD, exist_ok=True)
_c = {}


def s3():
    if 'c' not in _c:
        _c['c'] = boto3.client('s3', region_name='ap-south-1', config=Config(retries={'max_attempts': 20, 'mode': 'standard'}, max_pool_connections=96))
    return _c['c']


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


def san(s):
    return re.sub(r'[^A-Za-z0-9._-]+', '_', s)


def lst(prefix):
    out = []
    for page in s3().get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=prefix):
        out += page.get('Contents', [])
    return out


_NEED = {}


def one_result(key):
    """-> (rid, kind, needed nc1 shas of the archive, stored .nc1 keys or a prefix to list)"""
    if not _NEED:
        _NEED['s'] = pickle.load(open(os.path.join(INV, 'need_shas.pkl'), 'rb'))
    need = _NEED['s']
    p = os.path.join(RD, key.replace('/', '_'))
    for i in range(4):
        try:
            if not os.path.exists(p):
                s3().download_file(B, key, p + '.tmp'); os.replace(p + '.tmp', p)
            d = json.load(open(p)); break
        except Exception:
            if i == 3:
                return key, None, [], None
            time.sleep(2)
    shas = [h for h in ((d.get('sha256') or {}).get('nc1') or []) if h in need]
    if not shas:
        os.remove(p)
        return key, None, [], None
    if 'uploaded_objects' in d:
        keys = [k for k in d['uploaded_objects'] if k.lower().endswith('.nc1')]
        out = (key, 'ec2', shas, keys)
    else:
        pr = (d.get('proof_objects') or [None])[0]
        if pr and '/' in pr:
            pf = f'{D12}/' + '/'.join(pr.split('/')[:2]) + '/'
        else:
            disk, _, rest = (d.get('source_key') or '').partition('/')
            pf = f"{D12}/{disk}/{san(rest)}-{key.rsplit('/', 1)[-1][:12]}/"
        out = (key, 'gcp', shas, pf)
    os.remove(p)
    return out


def main():
    t0 = time.time()
    allj = '--all' in sys.argv
    pairs = json.load(open(os.path.join(INV, 'pairs.json')))
    need = {}
    for jid, o in pairs.items():
        if not allj and not o.get('steps'):
            continue
        for e in o['nc1_files']:
            if not e.get('key') and e['rel'] in ('inside_job', 'sibling', 'same_project'):
                need.setdefault(e['sha256'], (e['path'], e['size']))
    pickle.dump(set(need), open(os.path.join(INV, 'need_shas.pkl'), 'wb'))
    log(f'{len(need)} unresolved NC1 shas needed ({"all paired jobs" if allj else "jobs with a STEP"})')
    objs = [o['Key'] for o in lst(f'{D12}/_state/results/') + lst(f'{D12}/_state/ec2-results/') if o['Key'].endswith('.json')]
    sha2keys = collections.defaultdict(set); narch = 0; nkeys = 0
    with ProcessPoolExecutor(12) as ex:
        for key, kind, shas, keys in ex.map(one_result, objs, chunksize=4):
            if not kind:
                continue
            narch += 1
            if kind == 'gcp':
                keys = [o['Key'] for o in lst(keys) if o['Key'].lower().endswith('.nc1')]
            nkeys += len(keys)
            by = collections.defaultdict(list)
            for k in keys:
                by[k.rsplit('/', 1)[-1].lower()].append(k)
            for h in shas:
                base = san(need[h][0].rsplit('/', 1)[-1]).lower()
                for k in by.get(base, []):
                    sha2keys[h].add(k)
    log(f'{len(objs)} Disk-1/2 results; {narch} archives hold needed NC1; {nkeys} stored .nc1 keys; candidates for {len(sha2keys)} / {len(need)} shas ({time.time() - t0:.0f}s)')
    found = {}; how = collections.Counter()

    def verify(sha):
        path, size = need[sha]
        sp = san(path).lower()
        cands = sorted(sha2keys.get(sha, ()), key=lambda k: -len(os.path.commonprefix([k.lower()[::-1], sp[::-1]])))
        if not cands:
            return sha, None, 'no_candidate'
        for k in cands[:6]:
            try:
                b = s3().get_object(Bucket=B, Key=k)['Body'].read()
            except Exception:
                continue
            if hashlib.sha256(b).hexdigest() == sha:
                return sha, k, 'verified'
        return sha, None, 'sha_mismatch'
    with ThreadPoolExecutor(64) as ex:
        for sha, k, h in ex.map(verify, list(need)):
            how[h] += 1
            if k:
                found[sha] = k
    old = {}
    kp = os.path.join(INV, 'nc1_keys_d12.json')
    if os.path.exists(kp):
        old = json.load(open(kp))
    old.update(found)
    json.dump(old, open(kp, 'w'))
    s3().upload_file(kp, B, f'{RES}/inv/nc1_keys_d12.json')
    n = 0
    for o in pairs.values():
        for e in o['nc1_files']:
            if not e.get('key') and e['sha256'] in old:
                e['key'] = old[e['sha256']]; e['key_from'] = 'disk12_verified'; n += 1
    json.dump(pairs, open(os.path.join(INV, 'pairs.json'), 'w'))
    log(f'resolved {len(found)} / {len(need)} shas: {dict(how)}; pairs rows filled {n} ({time.time() - t0:.0f}s)')


if __name__ == '__main__':
    main()
