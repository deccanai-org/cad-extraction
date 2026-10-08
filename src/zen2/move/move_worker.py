#!/usr/bin/env python3
"""move_worker.py - move s3://annotationprod/cad-disk-extract/ -> s3://bim-proprietary-data/cad-disk-extract/ (identical keys).

MOVE_MODE:
  probe  permission checks (read/list both, write+delete a probe object in the destination) -> prints a report
  plan   discover shard prefixes by recursive delimiter listing (to depth MOVE_DEPTH below the root), pack them into
         chunk files _control/move/chunks/<cid>.json (shuffled), plus a flat shard for the objects directly under each prefix
  copy   claim a chunk -> for each shard: list the source (current versions) -> copy every object -> list the destination ->
         verify each key has the SAME size and the SAME ETag -> retry mismatches once -> result JSON per chunk.
         Single-part objects (ETag without '-', always < 5 GB): CopyObject (metadata + tags copied by S3).
         Multipart objects: our own multipart copy with the source's exact part layout (HeadObject PartNumber=1 gives the part
         size), so the destination ETag equals the source ETag. That makes ETag equality a full content check without reading data.
  purge  (only after a global reconcile) delete every version + delete marker of each verified shard's keys in the source.

State lives in the DESTINATION bucket: cad-disk-extract/_state/move/{claims,results,purged,hosts}/, control in _control/move/.
"""
import hashlib, json, math, os, random, socket, sys, threading, time, traceback
from concurrent.futures import ThreadPoolExecutor
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

SRC, DST, ROOT = 'annotationprod', 'bim-proprietary-data', 'cad-disk-extract/'
CTL, ST = ROOT + '_control/move/', ROOT + '_state/move/'
MODE = os.environ.get('MOVE_MODE', 'copy')
THREADS = int(os.environ.get('MOVE_THREADS', '96'))
DEPTH = int(os.environ.get('MOVE_DEPTH', '4'))
HOST = socket.gethostname()
PROC = os.environ.get('MOVE_PROC', 'p0')
CODE = 'move-2026-10-02v'
GB5 = 5 * 1024 ** 3

s3 = boto3.client('s3', region_name='ap-south-1', config=Config(max_pool_connections=THREADS + 32, connect_timeout=20,
                                                               read_timeout=300, retries={'max_attempts': 40, 'mode': 'standard'}))


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def put_json(key, obj, **kw):
    return s3.put_object(Bucket=DST, Key=key, Body=json.dumps(obj).encode(), ContentType='application/json', **kw)


def get_json(key, bucket=DST):
    try:
        return json.loads(s3.get_object(Bucket=bucket, Key=key)['Body'].read())
    except ClientError as e:
        if e.response['Error']['Code'] in ('NoSuchKey', '404'):
            return None
        raise


def keys_under(bucket, prefix):
    out, tok = [], None
    while True:
        kw = dict(Bucket=bucket, Prefix=prefix)
        if tok:
            kw['ContinuationToken'] = tok
        r = s3.list_objects_v2(**kw)
        out += [o['Key'] for o in r.get('Contents', [])]
        if not r.get('IsTruncated'):
            return out
        tok = r['NextContinuationToken']


def list_objects(bucket, prefix, flat):
    """list_objects with its own retry loop: a throttled listing (SlowDown / 503 after botocore's retries) is retried, not fatal."""
    for att in range(12):
        try:
            return _list_objects(bucket, prefix, flat)
        except ClientError as e:
            if att == 11 or e.response['Error']['Code'] not in ('SlowDown', '503', 'ServiceUnavailable', 'InternalError', 'RequestTimeout'):
                raise
        except Exception:
            if att == 11:
                raise
        time.sleep(min(60, 3 * 2 ** att) * (0.5 + random.random()))


def _list_objects(bucket, prefix, flat):
    """Current objects under prefix (flat=True: only those directly under it). -> {key: (size, etag)}"""
    out, tok = {}, None
    while True:
        kw = dict(Bucket=bucket, Prefix=prefix)
        if flat:
            kw['Delimiter'] = '/'
        if tok:
            kw['ContinuationToken'] = tok
        r = s3.list_objects_v2(**kw)
        for o in r.get('Contents', []):
            out[o['Key']] = (o['Size'], o['ETag'].strip('"'))
        if not r.get('IsTruncated'):
            return out
        tok = r['NextContinuationToken']


# ---------------------------------------------------------------- probe
def probe():
    rep = {}
    try:
        rep['src_list'] = len(s3.list_objects_v2(Bucket=SRC, Prefix=ROOT, MaxKeys=5).get('Contents', []))
    except Exception as e:
        rep['src_list'] = repr(e)[:200]
    try:
        rep['src_versions'] = len(s3.list_object_versions(Bucket=SRC, Prefix=ROOT + '_state/', MaxKeys=5).get('Versions', []))
    except Exception as e:
        rep['src_versions'] = repr(e)[:200]
    k = ST + f'_probe/{HOST}.txt'
    try:
        s3.put_object(Bucket=DST, Key=k, Body=b'probe')
        rep['dst_put'] = 'ok'
        src_key = s3.list_objects_v2(Bucket=SRC, Prefix=ROOT + '_state/', MaxKeys=1)['Contents'][0]['Key']
        s3.copy_object(Bucket=DST, Key=k + '.copy', CopySource={'Bucket': SRC, 'Key': src_key}, MetadataDirective='COPY')
        rep['copy_object'] = 'ok'
        s3.delete_object(Bucket=DST, Key=k)
        s3.delete_object(Bucket=DST, Key=k + '.copy')
        rep['dst_delete'] = 'ok'
    except Exception as e:
        rep['dst_error'] = repr(e)[:300]
    try:
        pk = ROOT + '_state/move_probe/' + HOST + '.txt'          # a probe object in the SOURCE: write, then purge its versions
        v = s3.put_object(Bucket=SRC, Key=pk, Body=b'probe').get('VersionId')
        s3.delete_object(Bucket=SRC, Key=pk, VersionId=v)
        vs = s3.list_object_versions(Bucket=SRC, Prefix=pk)
        rep['src_delete_version'] = 'ok' if not vs.get('Versions') and not vs.get('DeleteMarkers') else 'left: ' + str(vs)[:200]
    except Exception as e:
        rep['src_delete_version'] = repr(e)[:300]
    print(json.dumps(rep, indent=1), flush=True)
    put_json(ST + f'_probe/{HOST}.report.json', rep)


# ---------------------------------------------------------------- plan
def plan():
    t0 = time.time()
    shards, lock = [], threading.Lock()
    todo = [(ROOT, 0)]
    stats = {'listed_prefixes': 0}

    def level(item):
        prefix, depth = item
        subs, flat = [], 0
        tok = None
        while True:
            kw = dict(Bucket=SRC, Prefix=prefix, Delimiter='/')
            if tok:
                kw['ContinuationToken'] = tok
            r = s3.list_objects_v2(**kw)
            subs += [p['Prefix'] for p in r.get('CommonPrefixes', [])]
            flat += len(r.get('Contents', []))
            if not r.get('IsTruncated'):
                break
            tok = r['NextContinuationToken']
        new = []
        with lock:
            stats['listed_prefixes'] += 1
            if flat:
                shards.append({'prefix': prefix, 'flat': True})
            for s in subs:
                if s.startswith(CTL) or s.startswith(ST):
                    continue
                if depth + 1 < DEPTH:
                    new.append((s, depth + 1))
                else:
                    shards.append({'prefix': s, 'flat': False})
        return new

    with ThreadPoolExecutor(64) as ex:
        while todo:
            batch, todo = todo, []
            for new in ex.map(level, batch):
                todo += new
            print(now(), 'prefixes listed', stats['listed_prefixes'], 'shards', len(shards), 'queued', len(todo), flush=True)
    random.seed(7)
    random.shuffle(shards)
    for i, sh in enumerate(shards):
        sh['id'] = hashlib.sha1((sh['prefix'] + ('|flat' if sh['flat'] else '')).encode()).hexdigest()[:16]
    per = int(os.environ.get('MOVE_CHUNK', '400'))
    chunks = [shards[i:i + per] for i in range(0, len(shards), per)]
    for n, c in enumerate(chunks):
        put_json(CTL + f'chunks/c{n:05d}.json', {'id': f'c{n:05d}', 'shards': c})
    put_json(CTL + 'plan.json', {'at': now(), 'code': CODE, 'shards': len(shards), 'chunks': len(chunks), 'depth': DEPTH,
                                 'listed_prefixes': stats['listed_prefixes'], 'secs': round(time.time() - t0)})
    print('PLAN DONE shards', len(shards), 'chunks', len(chunks), 'in', round(time.time() - t0), 's', flush=True)


# ---------------------------------------------------------------- copy
def part_layout(key, size, etag):
    """Byte ranges reproducing the source's multipart layout (so the destination ETag equals the source ETag)."""
    n = int(etag.split('-')[1])
    p1 = s3.head_object(Bucket=SRC, Key=key, PartNumber=1)['ContentLength']
    if n == math.ceil(size / p1) and (n == 1 or p1 * (n - 1) < size):
        return [(i * p1, min(size, (i + 1) * p1) - 1) for i in range(n)]
    ranges, pos = [], 0                                            # non-uniform parts: read each part's size
    for i in range(1, n + 1):
        ln = s3.head_object(Bucket=SRC, Key=key, PartNumber=i)['ContentLength']
        ranges.append((pos, pos + ln - 1))
        pos += ln
    return ranges


def multipart_copy(key, size, etag):
    head = s3.head_object(Bucket=SRC, Key=key)
    ranges = part_layout(key, size, etag) if '-' in etag else \
        [(i, min(size, i + 512 * 2 ** 20) - 1) for i in range(0, size, 512 * 2 ** 20)]
    kw = {k: head[k] for k in ('ContentType', 'CacheControl', 'ContentDisposition', 'ContentEncoding', 'ContentLanguage') if head.get(k)}
    mpu = s3.create_multipart_upload(Bucket=DST, Key=key, Metadata=head.get('Metadata', {}), **kw)
    uid = mpu['UploadId']
    try:
        def part(i_r):
            i, (a, b) = i_r
            r = s3.upload_part_copy(Bucket=DST, Key=key, UploadId=uid, PartNumber=i + 1,
                                    CopySource={'Bucket': SRC, 'Key': key}, CopySourceRange=f'bytes={a}-{b}')
            return {'PartNumber': i + 1, 'ETag': r['CopyPartResult']['ETag']}
        with ThreadPoolExecutor(8) as ex:
            parts = list(ex.map(part, enumerate(ranges)))
        r = s3.complete_multipart_upload(Bucket=DST, Key=key, UploadId=uid, MultipartUpload={'Parts': parts})
        return r['ETag'].strip('"')
    except Exception:
        try:
            s3.abort_multipart_upload(Bucket=DST, Key=key, UploadId=uid)
        except Exception:
            pass
        raise


def copy_one(item):
    key, (size, etag) = item
    for attempt in range(4):
        try:
            if '-' not in etag and size < GB5:
                r = s3.copy_object(Bucket=DST, Key=key, CopySource={'Bucket': SRC, 'Key': key},
                                   MetadataDirective='COPY', TaggingDirective='COPY')
                with PLOCK:
                    PROG['copied'] += 1; PROG['bytes'] += size
                return key, r['CopyObjectResult']['ETag'].strip('"'), None
            new = multipart_copy(key, size, etag)
            with PLOCK:
                PROG['copied'] += 1; PROG['bytes'] += size
            return key, new, None
        except ClientError as e:
            code = e.response['Error']['Code']
            if code in ('NoSuchKey', '404'):
                return key, None, 'vanished'
            err = f'{code}: {str(e)[:150]}'
        except Exception as e:
            err = repr(e)[:180]
        time.sleep(min(30, 2 ** attempt) * (0.5 + random.random()))
    return key, None, err


def do_shard(sh, ex):
    src = list_objects(SRC, sh['prefix'], sh['flat'])
    have = list_objects(DST, sh['prefix'], sh['flat'])             # copy only what is missing or different
    todo = {k: v for k, v in src.items() if have.get(k) != v}
    res = dict(ex.map(lambda it: (lambda k, e, er: (k, (e, er)))(*copy_one(it)), todo.items()))
    dst = list_objects(DST, sh['prefix'], sh['flat'])
    bad = [k for k, (sz, et) in src.items() if dst.get(k) != (sz, et)]
    if bad:                                                        # one retry for anything missing / different
        for k, e, er in ex.map(copy_one, [(k, src[k]) for k in bad]):
            res[k] = (e, er)
        dst = list_objects(DST, sh['prefix'], sh['flat'])
        bad = [k for k, (sz, et) in src.items() if dst.get(k) != (sz, et)]
    vanished = [k for k, (e, er) in res.items() if er == 'vanished']
    bad = [k for k in bad if k not in vanished]
    return {'id': sh['id'], 'prefix': sh['prefix'], 'flat': sh['flat'], 'objects': len(src), 'copied_now': len(todo),
            'bytes': sum(v[0] for v in src.values()), 'verified': len(src) - len(bad) - len(vanished),
            'mismatch': len(bad), 'mismatch_keys': bad[:50], 'vanished': len(vanished),
            'multipart': sum(1 for v in src.values() if '-' in v[1]),
            'errors': [er for (e, er) in res.values() if er and er != 'vanished'][:20]}


def claim(cid):
    key = ST + f'claims/{cid}.json'
    body = {'host': HOST, 'proc': PROC, 'at': now(), 'ts': time.time()}
    try:
        put_json(key, body, IfNoneMatch='*')
        return True
    except ClientError as e:
        if e.response['Error']['Code'] not in ('PreconditionFailed', 'ConditionalRequestConflict'):
            raise
    try:                                                           # take over a stale claim (no heartbeat for 20 min)
        cur = s3.get_object(Bucket=DST, Key=key)
        old = json.loads(cur['Body'].read())
        if time.time() - old.get('ts', 0) > 180 and get_json(ST + f'results/{cid}.json') is None:
            put_json(key, body, IfMatch=cur['ETag'])
            return True
    except ClientError:
        pass
    return False


CURRENT = {'cid': None}
PROG = {'copied': 0, 'bytes': 0}
PLOCK = threading.Lock()


def heartbeat():
    while True:
        cid = CURRENT['cid']
        if cid:
            try:
                put_json(ST + f'claims/{cid}.json', {'host': HOST, 'proc': PROC, 'at': now(), 'ts': time.time()})
            except Exception:
                pass
        with PLOCK:
            print(now(), PROC, 'progress copied', PROG['copied'], 'bytes', PROG['bytes'], flush=True)
        time.sleep(60)


def copy_loop():
    threading.Thread(target=heartbeat, daemon=True).start()
    chunks = sorted(k.rsplit('/', 1)[-1][:-5] for k in keys_under(DST, CTL + 'chunks/'))
    random.seed(HOST + PROC)
    random.shuffle(chunks)
    with ThreadPoolExecutor(THREADS) as ex:
        while True:
            if get_json(CTL + 'stop', SRC) is not None:           # operator flags live in the SOURCE bucket (operator can write there)
                print(now(), PROC, 'stop flag', flush=True)
                return
            done = {k.rsplit('/', 1)[-1][:-5] for k in keys_under(DST, ST + 'results/')}
            todo = [c for c in chunks if c not in done]
            if not todo:
                print(now(), PROC, 'all chunks have results', flush=True)
                return
            picked = next((c for c in todo if claim(c)), None)
            if not picked:
                time.sleep(60)
                continue
            ch = get_json(CTL + f'chunks/{picked}.json')
            CURRENT['cid'] = picked
            t0, out = time.time(), []
            for sh in ch['shards']:
                try:
                    out.append(do_shard(sh, ex))
                except Exception:
                    out.append({'id': sh['id'], 'prefix': sh['prefix'], 'flat': sh['flat'], 'error': traceback.format_exc()[-800:]})
            summ = {'id': picked, 'host': HOST, 'proc': PROC, 'code': CODE, 'started': t0, 'finished': now(),
                    'secs': round(time.time() - t0), 'shards': out,
                    'objects': sum(s.get('objects', 0) for s in out), 'bytes': sum(s.get('bytes', 0) for s in out),
                    'verified': sum(s.get('verified', 0) for s in out), 'mismatch': sum(s.get('mismatch', 0) for s in out),
                    'shard_errors': sum(1 for s in out if 'error' in s)}
            put_json(ST + f'results/{picked}.json', summ)
            CURRENT['cid'] = None
            print(now(), PROC, picked, 'objects', summ['objects'], 'verified', summ['verified'], 'mismatch', summ['mismatch'],
                  'shard_errors', summ['shard_errors'], 'in', summ['secs'], 's', flush=True)


# ---------------------------------------------------------------- purge (source side, after global reconcile)
def purge_shard(sh):
    n, tok_k, tok_v = 0, None, None
    while True:
        kw = dict(Bucket=SRC, Prefix=sh['prefix'])
        if sh['flat']:
            kw['Delimiter'] = '/'
        if tok_k:
            kw['KeyMarker'] = tok_k
        if tok_v:
            kw['VersionIdMarker'] = tok_v
        r = s3.list_object_versions(**kw)
        objs = [{'Key': v['Key'], 'VersionId': v['VersionId']} for v in r.get('Versions', []) + r.get('DeleteMarkers', [])]
        for i in range(0, len(objs), 1000):
            d = s3.delete_objects(Bucket=SRC, Delete={'Objects': objs[i:i + 1000], 'Quiet': True})
            if d.get('Errors'):
                raise RuntimeError(str(d['Errors'][:3]))
            n += len(objs[i:i + 1000])
        if not r.get('IsTruncated'):
            return n
        tok_k, tok_v = r.get('NextKeyMarker'), r.get('NextVersionIdMarker')


def purge_loop():
    if get_json(CTL + 'purge_ok.json', SRC) is None:
        print('purge not authorised: s3://annotationprod/cad-disk-extract/_control/move/purge_ok.json missing', flush=True)
        return
    results = [k.rsplit('/', 1)[-1][:-5] for k in keys_under(DST, ST + 'results/')]
    random.seed(HOST + PROC)
    random.shuffle(results)
    with ThreadPoolExecutor(16) as ex:
        for cid in results:
            key = ST + f'purged/{cid}.json'
            try:
                put_json(key + '.claim', {'host': HOST, 'at': now()}, IfNoneMatch='*')
            except ClientError:
                continue
            res = get_json(ST + f'results/{cid}.json')
            ok = [s for s in res['shards'] if 'error' not in s and s.get('mismatch', 1) == 0]
            skipped = [s['prefix'] for s in res['shards'] if s not in ok]
            deleted = sum(ex.map(purge_shard, ok))
            put_json(key, {'id': cid, 'deleted_versions': deleted, 'skipped_shards': skipped, 'at': now()})
            print(now(), PROC, 'purged', cid, deleted, 'skipped', len(skipped), flush=True)


# ---------------------------------------------------------------- verified purge (owner-approved 2026-10-02)
VSKIP = (ROOT + '_control/',)                     # control files are purged last, separately, after the fleet reads bim
VST = ST + 'vpurged/'


def _src_versions(prefix, flat):
    """-> {key: {'versions': [(vid, size, etag, is_latest)], 'markers': [vid]}} for every key under prefix (flat: direct children)."""
    out, km, vm = {}, None, None
    while True:
        kw = dict(Bucket=SRC, Prefix=prefix)
        if flat:
            kw['Delimiter'] = '/'
        if km:
            kw['KeyMarker'] = km
        if vm:
            kw['VersionIdMarker'] = vm
        for att in range(12):
            try:
                r = s3.list_object_versions(**kw); break
            except ClientError as e:
                if att == 11:
                    raise
                time.sleep(min(60, 3 * 2 ** att) * (0.5 + random.random()))
        for v in r.get('Versions', []):
            out.setdefault(v['Key'], {'versions': [], 'markers': []})['versions'].append(
                (v['VersionId'], v['Size'], v['ETag'].strip('"'), v['IsLatest']))
        for m in r.get('DeleteMarkers', []):
            out.setdefault(m['Key'], {'versions': [], 'markers': []})['markers'].append(m['VersionId'])
        if not r.get('IsTruncated'):
            return out
        km, vm = r.get('NextKeyMarker'), r.get('NextVersionIdMarker')


def _delete(objs):
    n = 0
    for i in range(0, len(objs), 1000):
        part = objs[i:i + 1000]
        for att in range(8):
            try:
                d = s3.delete_objects(Bucket=SRC, Delete={'Objects': part, 'Quiet': True})
                if d.get('Errors'):
                    raise RuntimeError(str(d['Errors'][:3]))
                n += len(part); break
            except Exception:
                if att == 7:
                    raise
                time.sleep(min(30, 2 ** att) * (0.5 + random.random()))
    return n


def vpurge_shard(sh, ex):
    """Delete a source key's versions only when the destination holds the identical current object (same size + ETag).
    Missing / different -> copy the latest version first (same-ETag copy), re-verify, then delete. Keys with only delete markers
    (object already gone in the source) lose their markers. Anything that cannot be verified is kept and reported."""
    src = _src_versions(sh['prefix'], sh['flat'])
    dst = list_objects(DST, sh['prefix'], sh['flat'])
    deletable, fix, kept = [], {}, []
    for k, rec in src.items():
        latest = [v for v in rec['versions'] if v[3]]
        if not latest:                                   # only delete markers / noncurrent versions behind a marker
            if rec['versions'] and k not in dst:
                kept.append(k); continue                # noncurrent data that bim lacks: keep (never lose data)
            deletable.append(k); continue
        _, sz, et, _ = latest[0]
        if dst.get(k) == (sz, et):
            deletable.append(k)
        else:
            fix[k] = (sz, et)
    if fix:                                              # copy what bim lacks, then verify
        for k, e, er in ex.map(copy_one, list(fix.items())):
            pass
        dst2 = list_objects(DST, sh['prefix'], sh['flat'])
        for k, v in fix.items():
            (deletable if dst2.get(k) == v else kept).append(k)
    objs = []
    for k in deletable:
        rec = src[k]
        objs += [{'Key': k, 'VersionId': v[0]} for v in rec['versions']] + [{'Key': k, 'VersionId': m} for m in rec['markers']]
    n = _delete(objs) if objs else 0
    return {'prefix': sh['prefix'], 'flat': sh['flat'], 'keys': len(src), 'deleted_keys': len(deletable), 'deleted_versions': n,
            'copied_first': len(fix), 'kept': len(kept), 'kept_keys': kept[:50]}


def vpurge_loop():
    if get_json(CTL + 'purge_ok.json', SRC) is None:
        print('purge not authorised: s3://annotationprod/cad-disk-extract/_control/move/purge_ok.json missing', flush=True)
        return
    results = [k.rsplit('/', 1)[-1][:-5] for k in keys_under(DST, ST + 'results/')]
    random.seed(HOST + PROC + str(time.time()))
    random.shuffle(results)
    with ThreadPoolExecutor(THREADS) as ex, ThreadPoolExecutor(8) as shx:
        for cid in results:
            key = VST + f'{cid}.json'
            if get_json(key) is not None:
                continue
            try:
                put_json(key + '.claim', {'host': HOST, 'proc': PROC, 'at': now(), 'ts': time.time()}, IfNoneMatch='*')
            except ClientError:
                try:                                     # stale claim (> 30 min, no result) -> take over
                    cur = s3.get_object(Bucket=DST, Key=key + '.claim'); old = json.loads(cur['Body'].read())
                    if time.time() - old.get('ts', 0) < 1800:
                        continue
                    put_json(key + '.claim', {'host': HOST, 'proc': PROC, 'at': now(), 'ts': time.time()}, IfMatch=cur['ETag'])
                except ClientError:
                    continue
            res = get_json(ST + f'results/{cid}.json') or {}
            shards = [s for s in res.get('shards', []) if 'prefix' in s and not s['prefix'].startswith(VSKIP)]
            t0 = time.time()
            out = list(shx.map(lambda s: vpurge_shard(s, ex), shards))
            summ = {'id': cid, 'code': CODE, 'host': HOST, 'shards': len(out), 'deleted_keys': sum(o['deleted_keys'] for o in out),
                    'deleted_versions': sum(o['deleted_versions'] for o in out), 'copied_first': sum(o['copied_first'] for o in out),
                    'kept': sum(o['kept'] for o in out), 'kept_keys': [k for o in out for k in o['kept_keys']][:100],
                    'secs': round(time.time() - t0), 'at': now()}
            put_json(key, summ)
            print(now(), PROC, 'vpurged', cid, 'keys', summ['deleted_keys'], 'versions', summ['deleted_versions'],
                  'copied_first', summ['copied_first'], 'kept', summ['kept'], 'in', summ['secs'], 's', flush=True)


if __name__ == '__main__':
    {'probe': probe, 'plan': plan, 'copy': copy_loop, 'purge': purge_loop, 'vpurge': vpurge_loop}[MODE]()
