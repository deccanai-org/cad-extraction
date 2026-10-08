"""pdf_disk12_pass.py - classify the data-4 PDFs whose content lives only in the Disk-1 extraction (manifest key
'disk12:sha256:...'), by reading the Disk-1 copy at the key the old extraction worker used:
    cad-disk-extract/Disk-1/<safe_component(archive path minus first folder)[:240]>[-<12 hex> for GCP-phase folders]/<safe member path>
Also retries PDFs whose earlier read failed. Updates /work/pdfcache/classes.sqlite (the pdf_classify.py cache).
"""
import gzip, json, re, sqlite3, time, collections, threading
from concurrent.futures import ThreadPoolExecutor
import boto3
from botocore.config import Config

B = 'annotationprod'
Z4 = 'cad-disk-extract/zentitude-data-4'
s3 = boto3.client('s3', region_name='ap-south-1', config=Config(max_pool_connections=300, retries={'max_attempts': 8, 'mode': 'adaptive'}))
db = sqlite3.connect('/work/pdfcache/classes.sqlite', check_same_thread=False)
lock = threading.Lock()
src = open('/work/pdf_classify.py').read()
ns = {'re': re}
exec(src[src.index('CAD = re.compile'):src.index('def s3_class')], ns)
classify = ns['classify']


def safe_component(value):
    value = re.sub(r"[^A-Za-z0-9._!+\-]+", "_", value)
    return re.sub(r"_+", "_", value).strip("_") or "_"


def keys(prefix, delim=None):
    out, tok = [], None
    while True:
        kw = dict(Bucket=B, Prefix=prefix)
        if delim:
            kw['Delimiter'] = delim
        if tok:
            kw['ContinuationToken'] = tok
        r = s3.list_objects_v2(**kw)
        out += [o['Key'] for o in r.get('Contents', [])] + [p['Prefix'] for p in r.get('CommonPrefixes', [])]
        if not r.get('IsTruncated'):
            return out
        tok = r['NextContinuationToken']


folder_cache = {}


def disk1_folder(source_key):
    rest = source_key.split('/', 1)[1]
    tag = safe_component(rest)[:240]
    if tag in folder_cache:
        return folder_cache[tag]
    cands = [p for p in keys(f'cad-disk-extract/Disk-1/{tag}', '/') if p.endswith('/')]
    exact = f'cad-disk-extract/Disk-1/{tag}/'
    pick = exact if exact in cands else next((p for p in cands if re.match(re.escape(exact[:-1]) + r'-[0-9a-f]{12}/$', p)), None)
    folder_cache[tag] = pick
    return pick


def read_class(key):
    if key.startswith('MARKER:'):
        h = key[7:]
        try:
            key = s3.get_object(Bucket=B, Key=f'{Z4}/_state/sha/{h[:2]}/{h}')['Body'].read().decode()
        except Exception:
            return None
        if not key.startswith('cad-disk-extract/'):
            return None
    try:
        head = s3.get_object(Bucket=B, Key=key, Range='bytes=0-65535')['Body'].read()
        tail = s3.get_object(Bucket=B, Key=key, Range='bytes=-65536')['Body'].read() if len(head) == 65536 else b''
        return classify(head, tail)
    except s3.exceptions.NoSuchKey:
        return None
    except Exception:
        return 'unknown', 'read_error'


def main():
    t0 = time.time()
    jobs = {j['id']: j for j in json.loads(s3.get_object(Bucket=B, Key=f'{Z4}/_control/jobs.json')['Body'].read())}
    todo_cls = {sha for sha, in db.execute("SELECT sha FROM cls WHERE cls='unknown' AND why IN ('no_object','read_error','disk1:no_object')")}
    print('shas to (re)classify:', len(todo_cls), flush=True)
    work = {}          # sha -> candidate keys (Disk-1 copies or data-4 copies)
    mans = [k for k in keys(f'{Z4}/_state/manifests/') if k.endswith('.jsonl.gz')]

    def scan(mkey):
        jid = mkey.rsplit('/', 1)[-1].split('.')[0]
        j = jobs.get(jid)
        body = gzip.decompress(s3.get_object(Bucket=B, Key=mkey)['Body'].read())
        found = []
        for line in body.splitlines():
            if not line:
                continue
            e = json.loads(line)
            if not e['path'].lower().endswith('.pdf') or e['sha256'] not in todo_cls:
                continue
            if e['key'].startswith('cad-disk-extract/'):
                found.append((e['sha256'], e['key']))
            elif e['key'].startswith('sha256:'):
                found.append((e['sha256'], 'MARKER:' + e['sha256']))
            elif e['key'].startswith('disk12:') and j and j.get('phase') == 'B':
                folder = disk1_folder(j['key'])
                if folder:
                    found.append((e['sha256'], folder + '/'.join(safe_component(p) for p in e['path'].split('/'))))
        return found

    with ThreadPoolExecutor(32) as ex:
        for found in ex.map(scan, mans):
            for sha, key in found:
                work.setdefault(sha, []).append(key)
    print('shas with a readable candidate:', len(work), 'in', round(time.time() - t0), 's', flush=True)
    stats = collections.Counter()

    def one(item):
        sha, cands = item
        for key in cands[:3]:
            r = read_class(key)
            if r is not None:
                return sha, r
        return sha, ('unknown', 'no_object')

    items = list(work.items())
    import multiprocessing as mp
    N = 8
    for i in range(N):
        json.dump(items[i::N], open(f'/work/d12_todo_{i}.json', 'w'))
    procs = [mp.Process(target=classify_slice, args=(i,)) for i in range(N)]
    for p in procs: p.start()
    for p in procs: p.join()
    n = 0
    for i in range(N):
        rows = [l.rstrip('\n').split('\t') for l in open(f'/work/d12_done_{i}.tsv')]
        db.executemany('INSERT OR REPLACE INTO cls VALUES (?,?,?)', rows); n += len(rows)
        stats.update(r[1] for r in rows)
    db.commit()
    print('done in', round(time.time() - t0), 's', n, 'classified', dict(stats), flush=True)


def classify_slice(i):
    global s3
    s3 = boto3.client('s3', region_name='ap-south-1', config=Config(max_pool_connections=200, retries={'max_attempts': 8, 'mode': 'adaptive'}))
    items = json.load(open(f'/work/d12_todo_{i}.json'))

    def one(item):
        sha, cands = item
        for key in cands[:3]:
            r = read_class(key)
            if r is not None:
                c, w = r
                return f"{sha}\t{c}\t{('disk1:' + w) if not key.startswith('MARKER:') and '/Disk-1/' in key and w != 'read_error' else w}\n"
        return f"{sha}\tunknown\tdisk1:no_object\n"
    with open(f'/work/d12_done_{i}.tsv', 'w') as out, ThreadPoolExecutor(128) as ex:
        for line in ex.map(one, items):
            out.write(line)


if __name__ == '__main__':
    main()
