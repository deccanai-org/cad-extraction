"""s3cache.py - READ-ONLY S3 helpers with a local cache (used by make_jobs.py and presign.py).

Everything here is read-only against s3://bim-proprietary-data (AWS_PROFILE=bim, an IAM user with read access):
head_object, get_object, list_objects_v2.  Nothing in this module can write, copy or delete an S3 object.
Results are cached under jobs/cache/ so a re-run of make_jobs.py does not hit S3 again unless asked to.
"""
import gzip, hashlib, json, os, threading
from concurrent.futures import ThreadPoolExecutor

BUCKET = 'bim-proprietary-data'
REGION = 'ap-south-1'
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, 'cache')

_local = threading.local()


def session():
    import boto3
    return boto3.session.Session(profile_name=os.environ.get('AWS_PROFILE', 'bim'), region_name=REGION)


def client():
    """one boto3 client per thread (profile 'bim' unless AWS_PROFILE is already set); SigV4, regional endpoint"""
    c = getattr(_local, 's3', None)
    if c is None:
        import botocore.config
        c = session().client('s3', config=botocore.config.Config(
            signature_version='s3v4', retries={'max_attempts': 10, 'mode': 'adaptive'},
            max_pool_connections=8, connect_timeout=10, read_timeout=60, s3={'addressing_style': 'virtual'}))
        _local.s3 = c
    return c


def _ck(*parts):
    return hashlib.sha1('\x00'.join(parts).encode()).hexdigest()


def _obj(o):
    return {'key': o['Key'], 'bytes': o['Size'], 'etag': o['ETag'].strip('"'),
            'mtime': o['LastModified'].strftime('%Y-%m-%dT%H:%M:%SZ')}


def head(key):
    """{'key','bytes','etag','mtime'} or None when the object does not exist"""
    import botocore.exceptions
    try:
        h = client().head_object(Bucket=BUCKET, Key=key)
    except botocore.exceptions.ClientError as e:
        if e.response.get('Error', {}).get('Code') in ('404', 'NoSuchKey', 'NotFound'):
            return None
        raise
    return {'key': key, 'bytes': h['ContentLength'], 'etag': h['ETag'].strip('"'),
            'mtime': h['LastModified'].strftime('%Y-%m-%dT%H:%M:%SZ')}


def ls(prefix, delimiter=None):
    """uncached listing: (objects [{'key','bytes','etag','mtime'}], common prefixes [str])"""
    objs, dirs = [], []
    kw = {'Bucket': BUCKET, 'Prefix': prefix}
    if delimiter:
        kw['Delimiter'] = delimiter
    for pg in client().get_paginator('list_objects_v2').paginate(**kw):
        objs += [_obj(o) for o in pg.get('Contents', [])]
        dirs += [c['Prefix'] for c in pg.get('CommonPrefixes', [])]
    return objs, dirs


def get_bytes(key):
    """object body as bytes; None when the key does not exist (uncached)"""
    import botocore.exceptions
    try:
        return client().get_object(Bucket=BUCKET, Key=key)['Body'].read()
    except botocore.exceptions.ClientError as e:
        if e.response.get('Error', {}).get('Code') in ('404', 'NoSuchKey', 'NotFound'):
            return None
        raise


def get_text(key, sub, refresh=False):
    """object body (utf-8) cached at cache/<sub>/<sha1(key)>; None when the key does not exist"""
    d = os.path.join(CACHE, sub)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, _ck(key))
    miss = p + '.missing'
    if not refresh:
        if os.path.exists(p):
            return open(p, encoding='utf-8').read()
        if os.path.exists(miss):
            return None
    b = get_bytes(key)
    if b is None:
        open(miss, 'w').write(key)
        return None
    body = b.decode('utf-8')
    with open(p + '.tmp', 'w', encoding='utf-8') as f:
        f.write(body)
    os.replace(p + '.tmp', p)
    if os.path.exists(miss):
        os.remove(miss)
    return body


def cached_path(key, sub):
    """where get_text caches key (may not exist)"""
    return os.path.join(CACHE, sub, _ck(key))


def list_prefix(prefix, sub, refresh=False):
    """all objects under prefix -> {key: {'size', 'etag', 'mtime'}}, cached gz-json at cache/<sub>/<sha1(prefix)>.json.gz"""
    d = os.path.join(CACHE, sub)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, _ck(prefix) + '.json.gz')
    if os.path.exists(p) and not refresh:
        with gzip.open(p, 'rt') as f:
            return json.load(f)['objects']
    objs, _ = ls(prefix)
    out = {o['key']: {'size': o['bytes'], 'etag': o['etag'], 'mtime': o['mtime']} for o in objs}
    with gzip.open(p + '.tmp', 'wt') as f:
        json.dump({'prefix': prefix, 'objects': out}, f)
    os.replace(p + '.tmp', p)
    return out


def list_dirs(prefix, sub, refresh=False):
    """common prefixes one level below prefix (Delimiter='/'), cached"""
    d = os.path.join(CACHE, sub)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, _ck('dirs', prefix) + '.json')
    if os.path.exists(p) and not refresh:
        return json.load(open(p))
    _, out = ls(prefix, '/')
    json.dump(out, open(p + '.tmp', 'w'))
    os.replace(p + '.tmp', p)
    return out


def pmap(fn, items, workers=48):
    with ThreadPoolExecutor(workers) as ex:
        return list(ex.map(fn, items))


def head_sha256(key):
    """{'sha256': hex | None, 'type': FULL_OBJECT | COMPOSITE | None, 'bytes', 'etag'} from the object's stored S3 checksum
    (HEAD with ChecksumMode=ENABLED; read-only); None when the object does not exist"""
    import base64, botocore.exceptions
    try:
        h = client().head_object(Bucket=BUCKET, Key=key, ChecksumMode='ENABLED')
    except botocore.exceptions.ClientError as e:
        if e.response.get('Error', {}).get('Code') in ('404', 'NoSuchKey', 'NotFound'):
            return None
        raise
    cs, typ = h.get('ChecksumSHA256'), h.get('ChecksumType')
    full = cs and '-' not in cs and typ in (None, 'FULL_OBJECT')
    return {'sha256': base64.b64decode(cs).hex() if full else None, 'type': typ, 'bytes': h['ContentLength'],
            'etag': h['ETag'].strip('"')}
