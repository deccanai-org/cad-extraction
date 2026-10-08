"""z4_marker_audit.py - find data-4 content whose disk-wide sha marker points to an object that was never uploaded.
Cause: upload_tree writes the marker (conditional PUT) BEFORE uploading; a worker killed in between (hot reload, stop, crash, box
release) leaves the marker; the re-run sees the marker, records a 'sha256:' pointer and skips the upload.
Pass 1 (all manifests, 32 procs): shas (>= 64 KB) that occur ONLY as 'sha256:' pointers, never as a stored key in any manifest.
Pass 2: read each candidate's marker, HEAD its target -> missing list (sha, marker target) -> _state/audit/marker_missing.json.
Pass 3: every manifest occurrence of a missing sha (job, path, size) -> _state/audit/marker_missing_occurrences.jsonl.gz."""
import gzip, json, os, time, collections, multiprocessing as mp
from concurrent.futures import ThreadPoolExecutor
import boto3
from botocore.config import Config

B, Z4 = 'annotationprod', 'cad-disk-extract/zentitude-data-4'
SMALL = 65536
OUT = os.environ.get('AUDIT_OUT', 'marker_missing')      # e.g. marker_missing_after_repair


def client():
    return boto3.client('s3', region_name='ap-south-1', config=Config(max_pool_connections=128, retries={'max_attempts': 5, 'mode': 'standard'}, connect_timeout=20, read_timeout=60))


def manifests(s3):
    out, tok = [], None
    while True:
        kw = dict(Bucket=B, Prefix=f'{Z4}/_state/manifests/')
        if tok:
            kw['ContinuationToken'] = tok
        r = s3.list_objects_v2(**kw)
        out += [o['Key'] for o in r.get('Contents', []) if o['Key'].endswith('.jsonl.gz')]
        if not r.get('IsTruncated'):
            return out
        tok = r['NextContinuationToken']


def load(mkey):
    return gzip.decompress(client().get_object(Bucket=B, Key=mkey)['Body'].read()).splitlines()


def scan(mkey):
    stored, ptr = set(), set()
    for line in load(mkey):
        if not line:
            continue
        e = json.loads(line)
        if e['size'] < SMALL:
            continue
        k = e['key']
        if k.startswith('sha256:'):
            ptr.add(bytes.fromhex(e['sha256']))
        elif k.startswith('cad-disk-extract/') and not e.get('dedup'):
            stored.add(bytes.fromhex(e['sha256']))
    return stored, ptr


def check_chunk(shas):
    s3 = client()

    def check(sha):
        try:
            tgt = s3.get_object(Bucket=B, Key=f'{Z4}/_state/sha/{sha[:2]}/{sha}')['Body'].read().decode().strip()
        except Exception:
            return sha, None, 'no_marker'
        try:
            s3.head_object(Bucket=B, Key=tgt)
            return sha, tgt, 'ok'
        except Exception as e:
            return sha, tgt, 'missing' if '404' in str(e) or 'Not Found' in str(e) else 'head_error'
    with ThreadPoolExecutor(32) as ex:
        return list(ex.map(check, shas))


def occ(args):
    mkey, miss = args
    jid = mkey.rsplit('/', 1)[-1].split('.')[0]
    out = []
    for line in load(mkey):
        if line:
            e = json.loads(line)
            if e['size'] >= SMALL and e['sha256'] in miss:
                out.append({'job': jid, 'path': e['path'], 'size': e['size'], 'sha256': e['sha256'], 'key': e['key']})
    return out


if __name__ == '__main__':
    t0 = time.time(); s3 = client()
    mans = manifests(s3)
    stored, ptr = set(), set()
    with mp.Pool(32) as pool:
        for i, (st, pt) in enumerate(pool.imap_unordered(scan, mans, chunksize=4)):
            stored |= st; ptr |= pt
            if i % 200 == 0:
                print(time.strftime('%H:%M:%S'), 'manifests', i, '/', len(mans), 'stored', len(stored), 'ptr', len(ptr), flush=True)
    cand = [c.hex() for c in ptr - stored]
    print('pass1: stored shas', len(stored), '| pointer shas', len(ptr), '| pointer-only candidates', len(cand), round(time.time() - t0), 's', flush=True)
    del stored, ptr

    json.dump(cand, open('/work/audit_cand.json', 'w'))
    st = collections.Counter(); missing = {}
    chunks = [cand[i:i + 5000] for i in range(0, len(cand), 5000)]
    with mp.Pool(16) as pool:
        for i, res in enumerate(pool.imap_unordered(check_chunk, chunks)):
            for sha, tgt, r in res:
                st[r] += 1
                if r != 'ok':
                    missing[sha] = [tgt, r]
            if i % 5 == 0:
                print(time.strftime('%H:%M:%S'), 'pass2 chunks', i + 1, '/', len(chunks), dict(st), flush=True)
    print('pass2:', dict(st), round(time.time() - t0), 's', flush=True)
    s3.put_object(Bucket=B, Key=f'{Z4}/_state/audit/{OUT}.json', Body=json.dumps({'updated': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                  'candidates': len(cand), 'result': dict(st), 'missing': missing}).encode())
    miss = set(missing)
    rows = []
    with mp.Pool(32) as pool:
        for r in pool.imap_unordered(occ, [(m, miss) for m in mans], chunksize=4):
            rows += r
    jobs = collections.Counter(r['job'] for r in rows)
    first = {}
    for r in rows:
        first.setdefault(r['sha256'], r['size'])
    print('pass3: occurrences', len(rows), '| distinct missing', len(first), '| bytes (distinct)', sum(first.values()), '| archives', len(jobs), flush=True)
    ext = collections.Counter(r['path'].rsplit('.', 1)[-1].lower()[:10] for r in rows if '.' in r['path'])
    print('top extensions:', ext.most_common(15), flush=True)
    s3.put_object(Bucket=B, Key=f'{Z4}/_state/audit/{OUT}_occurrences.jsonl.gz', Body=gzip.compress('\n'.join(json.dumps(r) for r in rows).encode()))
    print('DONE', round(time.time() - t0), 's', flush=True)
