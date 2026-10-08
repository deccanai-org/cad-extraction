cat > /work/pdf_slice_retry.py <<'__EOF__'
"""pdf_slice_retry.py N - re-run one slice of pdf_disk12_parallel.py with per-request timeouts and completion-order output
(one hung read can no longer block the slice), then merge the results into /work/pdfcache/classes.sqlite."""
import json, sqlite3, sys, time, re
from concurrent.futures import ThreadPoolExecutor, as_completed
import boto3
from botocore.config import Config

N = int(sys.argv[1])
B, Z4 = 'annotationprod', 'cad-disk-extract/zentitude-data-4'
s3 = boto3.client('s3', region_name='ap-south-1', config=Config(max_pool_connections=200, connect_timeout=20, read_timeout=30,
                                                                 retries={'max_attempts': 3, 'mode': 'standard'}))
src = open('/work/pdf_classify.py').read()
ns = {'re': re}
exec(src[src.index('CAD = re.compile'):src.index('def s3_class')], ns)
classify = ns['classify']


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
        return classify(head, tail), key
    except s3.exceptions.NoSuchKey:
        return None
    except Exception:
        return ('unknown', 'read_error'), key


def one(item):
    sha, cands = item
    for key in cands[:3]:
        r = read_class(key)
        if r is not None:
            (c, w), k = r
            return sha, c, (('disk1:' + w) if '/Disk-1/' in k and w != 'read_error' else w)
    return sha, 'unknown', 'disk1:no_object'


items = json.load(open(f'/work/d12_todo_{N}.json'))
t0 = time.time(); rows = []
with ThreadPoolExecutor(128) as ex:
    futs = [ex.submit(one, it) for it in items]
    for i, f in enumerate(as_completed(futs)):
        try:
            rows.append(f.result())
        except Exception:
            pass
        if i % 20000 == 0:
            print(time.strftime('%H:%M:%S'), i, '/', len(items), flush=True)
db = sqlite3.connect('/work/pdfcache/classes.sqlite')
db.executemany('INSERT OR REPLACE INTO cls VALUES (?,?,?)', rows)
db.commit()
print('slice', N, 'classified', len(rows), 'of', len(items), 'in', round(time.time() - t0), 's', flush=True)
print(db.execute('SELECT cls, COUNT(*) FROM cls GROUP BY cls').fetchall(), flush=True)
__EOF__
cat > /work/run_slice0.sh <<'__EOF__'
#!/bin/bash
# stop only the slice-0 child (the process holding d12_done_0.tsv open), let the pass merge 1-7, then retry slice 0
for p in $(pgrep -f pdf_disk12_parallel.py); do ls -l /proc/$p/fd 2>/dev/null | grep -q d12_done_0.tsv && kill $p && echo "killed slice-0 child $p"; done
while pgrep -f pdf_disk12_parallel.py > /dev/null; do sleep 5; done
sleep 5; pkill -f /work/pdf_classify.py; sleep 2
python3 /work/pdf_slice_retry.py 0 > /work/pdf_slice0.out 2>&1
setsid nohup python3 /work/pdf_classify.py > /work/pdf_classify.out 2>&1 < /dev/null &
echo "slice-0 retry done; classifier restarted"
__EOF__
chmod +x /work/run_slice0.sh; echo staged
