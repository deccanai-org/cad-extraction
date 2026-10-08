"""s3copy.py MANIFEST.json LIST_KEY SRC_BUCKET SRC_STRIP DST_PREFIX STATE_KEY [threads]

Server-side copy (data never leaves S3) of the keys in MANIFEST[LIST_KEY] from SRC_BUCKET into
s3://annotationprod/DST_PREFIX/<key minus SRC_STRIP>. Runs with the laptop's `bim` identity, which can read the
source bucket (the EC2 role cannot). Resumable: a destination object with the same size is skipped.
Progress JSON is written to s3://annotationprod/STATE_KEY every 30 s for the status page.
"""
import json, sys, time, threading, boto3
from concurrent.futures import ThreadPoolExecutor, as_completed
from boto3.s3.transfer import TransferConfig
from botocore.config import Config

man, list_key, src_bucket, strip, dst_prefix, state_key = sys.argv[1:7]
threads = int(sys.argv[7]) if len(sys.argv) > 7 else 24
DST = 'annotationprod'
keys = json.load(open(man))[list_key]
s3 = boto3.Session(profile_name='bim').client('s3', region_name='ap-south-1',
                                              config=Config(max_pool_connections=threads * 10 + 20, retries={'max_attempts': 10, 'mode': 'standard'}))
tc = TransferConfig(multipart_threshold=64 * 2**20, multipart_chunksize=256 * 2**20, max_concurrency=8)
lock = threading.Lock()
st = {'started': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'total_objects': len(keys), 'total_bytes': 0,
      'done_objects': 0, 'done_bytes': 0, 'skipped_objects': 0, 'failed': [], 'src': f's3://{src_bucket}/{strip}', 'dst': f's3://{DST}/{dst_prefix}/'}


def dst_key(k):
    return f"{dst_prefix}/{k[len(strip):].lstrip('/')}"


def size_of(bucket, key):
    try:
        return s3.head_object(Bucket=bucket, Key=key)['ContentLength']
    except Exception:
        return None


def one(k):
    sz = size_of(src_bucket, k)
    if sz is None:
        return k, 'missing', 0
    with lock:
        st['total_bytes'] += sz
    if size_of(DST, dst_key(k)) == sz:
        return k, 'skip', sz
    s3.copy({'Bucket': src_bucket, 'Key': k}, DST, dst_key(k), Config=tc)
    return k, 'ok', sz


def publish(final=False):
    with lock:
        st['updated'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        st['final'] = final
        body = json.dumps(st, indent=1)
    try:
        s3.put_object(Bucket=DST, Key=state_key, Body=body.encode(), ContentType='application/json')
    except Exception as e:
        print('publish failed', e, flush=True)


stop = threading.Event()
def ticker():
    while not stop.wait(30):
        publish()
        print(f"{st['updated']} {st['done_objects'] + st['skipped_objects']}/{st['total_objects']} objs, "
              f"{st['done_bytes'] / 1e9:,.1f} GB copied, {len(st['failed'])} failed", flush=True)
threading.Thread(target=ticker, daemon=True).start()

with ThreadPoolExecutor(threads) as ex:
    futs = {ex.submit(one, k): k for k in keys}
    for f in as_completed(futs):
        k = futs[f]
        try:
            _, how, sz = f.result()
            with lock:
                if how == 'ok':
                    st['done_objects'] += 1; st['done_bytes'] += sz
                elif how == 'skip':
                    st['skipped_objects'] += 1
                else:
                    st['failed'].append([k, how])
        except Exception as e:
            with lock:
                st['failed'].append([k, str(e)[:300]])
stop.set(); publish(final=True)
print('DONE', json.dumps({x: st[x] for x in ('total_objects', 'done_objects', 'skipped_objects', 'done_bytes')}), 'failed', len(st['failed']), flush=True)
