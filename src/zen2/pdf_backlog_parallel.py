"""pdf_backlog_parallel.py - classify every data-4 PDF not yet in /work/pdfcache/classes.sqlite, using 8 processes.
1) list manifests, load/refresh the per-archive caches ([sha, key, worker_class]), take the worker's class where present,
2) split the remaining (sha, real S3 key) list over 8 processes (head/tail 64 KB range reads, same rules as pdf_classify.py),
3) merge into classes.sqlite. Afterwards pdf_classify.py publishes the tally (it will find everything classified).
"""
import gzip, json, os, re, sqlite3, time, multiprocessing as mp
from concurrent.futures import ThreadPoolExecutor
import boto3
from botocore.config import Config

B = 'annotationprod'
Z4 = 'cad-disk-extract/zentitude-data-4'
C = '/work/pdfcache'
src = open('/work/pdf_classify.py').read()
ns = {'re': re}
exec(src[src.index('CAD = re.compile'):src.index('def s3_class')], ns)
classify = ns['classify']


def client():
    return boto3.client('s3', region_name='ap-south-1', config=Config(max_pool_connections=200, retries={'max_attempts': 8, 'mode': 'adaptive'}))


def manifest_rows(args):
    s3, jid = args
    cf = f'{C}/{jid}.json'
    if os.path.exists(cf):
        rows = json.load(open(cf))
        if all(len(r) == 3 for r in rows):
            return rows
    body = gzip.decompress(s3.get_object(Bucket=B, Key=f'{Z4}/_state/manifests/{jid}.jsonl.gz')['Body'].read())
    rows = []
    for line in body.splitlines():
        if line:
            e = json.loads(line)
            if e['path'].lower().endswith('.pdf') and e['size'] > 0:
                rows.append([e['sha256'], e['key'], e.get('pdf_class')])
    json.dump(rows, open(cf, 'w'))
    return rows


def work(slice_file, out_file):
    s3 = client()
    items = [l.rstrip('\n').split('\t') for l in open(slice_file)]

    def one(it):
        sha, key = it
        try:
            head = s3.get_object(Bucket=B, Key=key, Range='bytes=0-65535')['Body'].read()
            tail = s3.get_object(Bucket=B, Key=key, Range='bytes=-65536')['Body'].read() if len(head) == 65536 else b''
            c, w = classify(head, tail)
        except Exception:
            c, w = 'unknown', 'read_error'
        return f'{sha}\t{c}\t{w}\n'
    with open(out_file, 'w') as out, ThreadPoolExecutor(128) as ex:
        for line in ex.map(one, items):
            out.write(line)


if __name__ == '__main__':
    t0 = time.time()
    s3 = client()
    db = sqlite3.connect(f'{C}/classes.sqlite')
    known = {sha for (sha,) in db.execute("SELECT sha FROM cls WHERE why != 'read_error'")}
    mans, tok = [], None
    while True:
        kw = dict(Bucket=B, Prefix=f'{Z4}/_state/manifests/')
        if tok:
            kw['ContinuationToken'] = tok
        r = s3.list_objects_v2(**kw)
        mans += [o['Key'].rsplit('/', 1)[-1].split('.')[0] for o in r.get('Contents', [])]
        if not r.get('IsTruncated'):
            break
        tok = r['NextContinuationToken']
    first, given = {}, {}
    with ThreadPoolExecutor(32) as ex:
        for rows in ex.map(manifest_rows, [(s3, j) for j in mans]):
            for sha, key, cls in rows:
                if sha in known:
                    continue
                if cls:
                    given[sha] = cls
                if key.startswith('cad-disk-extract/') and sha not in first:
                    first[sha] = key
    db.executemany('INSERT OR REPLACE INTO cls VALUES (?,?,?)', [(s, c, 'worker') for s, c in given.items()])
    db.commit()
    todo = [(s, k) for s, k in first.items() if s not in given]
    print('manifests', len(mans), '| worker-classified', len(given), '| to read from S3', len(todo), 'in', round(time.time() - t0), 's', flush=True)
    N = 8
    for i in range(N):
        with open(f'/work/pdf_todo_{i}.tsv', 'w') as f:
            f.writelines(f'{s}\t{k}\n' for s, k in todo[i::N])
    procs = [mp.Process(target=work, args=(f'/work/pdf_todo_{i}.tsv', f'/work/pdf_done_{i}.tsv')) for i in range(N)]
    for p in procs:
        p.start()
    for p in procs:
        p.join()
    n = 0
    for i in range(N):
        rows = [l.rstrip('\n').split('\t') for l in open(f'/work/pdf_done_{i}.tsv')]
        db.executemany('INSERT OR REPLACE INTO cls VALUES (?,?,?)', rows)
        n += len(rows)
    db.commit()
    print('classified from S3', n, '| total time', round(time.time() - t0), 's', flush=True)
    print(db.execute('SELECT cls, COUNT(*) FROM cls GROUP BY cls').fetchall(), flush=True)
