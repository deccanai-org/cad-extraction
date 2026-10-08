cat > /work/dedup_disk12_dryrun.py <<'__EOF__'
"""dedup_disk12_dryrun.py - DRY RUN: which objects stored under zentitude-data-4/extracted/ hold content that Disk-1/Disk-2
already stored (sha256 in union.sqlite)? Nothing is deleted. Writes, per finished archive, the candidate list
(key, size, sha256) to _state/dedup_disk12/candidates/<id>.jsonl.gz and totals to _state/dedup_disk12/summary.json.
A later (confirmed) run deletes those objects, rewrites every manifest entry with that sha256 to 'disk12:sha256:<hash>'
and repoints the matching _state/sha/ marker, so no pointer breaks.
"""
import array, bisect, gzip, json, time, collections
from concurrent.futures import ThreadPoolExecutor
import boto3

B = 'annotationprod'
Z4 = 'cad-disk-extract/zentitude-data-4'
s3 = boto3.client('s3', region_name='ap-south-1')
IDX = array.array('Q')
IDX.frombytes(open('/work/idx/disk12_sha64.bin', 'rb').read())


def hit(sha):
    h = int(sha[:16], 16)
    i = bisect.bisect_left(IDX, h)
    return i < len(IDX) and IDX[i] == h


def keys(prefix):
    out, tok = [], None
    while True:
        kw = dict(Bucket=B, Prefix=prefix)
        if tok:
            kw['ContinuationToken'] = tok
        r = s3.list_objects_v2(**kw)
        out += [o['Key'] for o in r.get('Contents', [])]
        if not r.get('IsTruncated'):
            return out
        tok = r['NextContinuationToken']


def one(mkey):
    jid = mkey.rsplit('/', 1)[-1].split('.')[0]
    body = gzip.decompress(s3.get_object(Bucket=B, Key=mkey)['Body'].read())
    cand = []
    for line in body.splitlines():
        if not line:
            continue
        e = json.loads(line)
        if not e.get('dedup') and e['size'] > 0 and e['key'].startswith(Z4 + '/extracted/') and hit(e['sha256']):
            cand.append({'key': e['key'], 'size': e['size'], 'sha256': e['sha256']})
    if cand:
        s3.put_object(Bucket=B, Key=f'{Z4}/_state/dedup_disk12/candidates/{jid}.jsonl.gz',
                      Body=gzip.compress('\n'.join(json.dumps(c) for c in cand).encode()))
    return jid, len(cand), sum(c['size'] for c in cand)


if __name__ == '__main__':
    t0 = time.time()
    mans = [k for k in keys(f'{Z4}/_state/manifests/') if k.endswith('.jsonl.gz')]
    with ThreadPoolExecutor(32) as ex:
        res = list(ex.map(one, mans))
    tot_files = sum(r[1] for r in res); tot_bytes = sum(r[2] for r in res)
    summ = {'dry_run': True, 'updated': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'archives_scanned': len(mans),
            'archives_with_candidates': sum(1 for r in res if r[1]), 'objects_to_remove': tot_files, 'bytes_to_remove': tot_bytes,
            'rule': 'stored object whose sha256 (first 8 bytes) is in the Disk-1/Disk-2 union index; the content is kept in the Disk-1/2 extraction'}
    s3.put_object(Bucket=B, Key=f'{Z4}/_state/dedup_disk12/summary.json', Body=json.dumps(summ, indent=1).encode(), ContentType='application/json')
    print(json.dumps(summ), 'in', round(time.time() - t0), 's')
__EOF__
python3 /work/dedup_disk12_dryrun.py 2>&1 | grep -v -i warn | tail -2
