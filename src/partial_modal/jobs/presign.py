#!/usr/bin/env python3
"""presign.py - job row(s) -> pre-signed S3 GET URLs (SigV4, up to 7 days) for every input a Modal job reads.

Runs on the Mac with AWS_PROFILE=bim (read-only IAM user, long-term keys -> a URL really lives the full 7 days; with
temporary/session credentials a URL dies with the session, so this tool refuses those unless --allow-session-creds).
Modal never sees AWS credentials: it only receives these URLs.  Nothing here writes to S3.

  python jobs/presign.py --jobs jobs/new5.jsonl --check --test --out jobs/urls/new5.urls.json \
                         --embed-out jobs/urls/new5.signed.jsonl
  python jobs/presign.py --jobs jobs/jobs_partial.jsonl.gz --ids <mid>,<mid> ...   # any subset (or --tags n1_db1_small,...)

Per job the URL set is (names are stable; the app reads them by name):
  step                    the delivered STEP in the package (model/step/...) - what we verify against and colour
  source                  the source file: package/add-on IFC (.ifc/.ifczip/.ifcXML), DB1 (.db1) or SDS/2 job (.zip)
  detail/<alias>          the conversion-detail files proven to belong to the shipped conversion run (job.detail_keys):
                          IFC/DB1 parts_json, check_json, results_json, src_parts, step_parts, census, (IFC) stats_json,
                          attrib, result_detail, (DB1) decoded_parts; SDS/2 pieces_csv, skipped_csv, log, manifest_json,
                          job_json, results_json (only when it describes the shipped run)
  --detail all            additionally conv/<file> and state/<file> for every side file found, even the ones that belong
                          to another conversion run (flagged matches_shipped=false in the output)
  --png                   include render_png (off by default: not needed by the pipeline)

--check  HEAD every key first: size and ETag must equal the job row (the job list is a snapshot; a changed object
         means the job row is stale -> exit 2, nothing signed for that job unless --allow-changed)
--test   ranged GET (bytes 0-15) of every signed URL with plain HTTPS, no credentials: proves each URL works
The URL file is written 0600 and the URLs are never printed (they are bearer tokens for 7 days).
"""
import argparse, datetime, gzip, json, os, sys, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import s3cache  # noqa: E402

MAX_EXPIRES = 7 * 24 * 3600            # SigV4 pre-signed URL maximum (604800 s)
PRESIGN_V = 'pmp-presign-2026-10-07a'


def read_jobs(path):
    op = gzip.open if path.endswith('.gz') else open
    with op(path, 'rt') as f:
        return [json.loads(l) for l in f if l.strip()]


def _meta(job):
    """key -> (bytes, etag, matches_shipped, name) for every file the job row knows"""
    m = {}
    for o in job['conv'].get('files', []):
        m[o['key']] = (o.get('bytes'), o.get('etag'), True, 'conv/' + o['key'].rsplit('/', 1)[1])
    st = job.get('state') or {}
    if st.get('results'):
        o = st['results']
        m[o['key']] = (o.get('bytes'), o.get('etag'), o.get('matches_shipped'), 'state/' + o['key'].rsplit('/', 1)[1])
    for o in st.get('files', []):
        m[o['key']] = (o.get('bytes'), o.get('etag'), o.get('matches_shipped'), 'state/' + o['key'].rsplit('/', 1)[1])
    return m


def job_keys(job, detail='shipped', png=False):
    """{name: {'key', 'bytes', 'etag', 'matches_shipped'}} - the inputs one job reads, in a stable order"""
    out = {'step': {'key': job['step']['key'], 'bytes': job['step']['bytes'], 'etag': job['step']['etag'],
                    'matches_shipped': True}}
    src = job['source']
    if src.get('key') and src.get('exists'):
        out['source'] = {'key': src['key'], 'bytes': src.get('bytes'), 'etag': src.get('etag'), 'matches_shipped': True}
    meta = _meta(job)
    if detail in ('shipped', 'all'):
        for alias in sorted(job.get('detail_keys', {})):
            if alias == 'render_png' and not png:
                continue
            k = job['detail_keys'][alias]
            b, e, ok, _ = meta.get(k, (None, None, True, None))
            out['detail/' + alias] = {'key': k, 'bytes': b, 'etag': e, 'matches_shipped': ok}
    if detail == 'all':
        have = {v['key'] for v in out.values()}
        for k in sorted(meta):
            b, e, ok, name = meta[k]
            if k in have or (k.endswith('.png') and not png):
                continue
            out[name] = {'key': k, 'bytes': b, 'etag': e, 'matches_shipped': ok}
    return out


def credential_kind():
    c = s3cache.session().get_credentials()
    if c is None:
        raise SystemExit('presign.py: no AWS credentials (AWS_PROFILE=bim expected)')
    fz = c.get_frozen_credentials()
    return 'session_temporary' if fz.token else 'long_term_access_key'


def presign_job(job, expires=MAX_EXPIRES, detail='shipped', png=False, check=False, client=None):
    """one job -> {'model_id', 'expires_at', 'urls': {name: {key, bytes, etag, url}}, 'check': {...}}"""
    s3 = client or s3cache.client()
    keys = job_keys(job, detail, png)
    res = {'model_id': job['model_id'], 'pid': job['pid'], 'model_folder': job['model_folder'],
           'generated_at': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
           'expires_s': expires, 'urls': {}, 'check': {}}
    res['expires_at'] = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=expires)
                         ).strftime('%Y-%m-%dT%H:%M:%SZ')
    for name, k in keys.items():
        if check:
            h = s3cache.head(k['key'])
            if h is None:
                res['check'][name] = 'missing'
            elif (k['bytes'] is not None and h['bytes'] != k['bytes']) or (k['etag'] and h['etag'] != k['etag']):
                res['check'][name] = f'changed: bytes {k["bytes"]}->{h["bytes"]} etag {k["etag"]}->{h["etag"]}'
            else:
                res['check'][name] = 'ok'
        url = s3.generate_presigned_url('get_object', Params={'Bucket': s3cache.BUCKET, 'Key': k['key']},
                                        ExpiresIn=expires, HttpMethod='GET')
        res['urls'][name] = dict(k, url=url)
    return res


def test_url(url, want_bytes=None, timeout=60):
    """ranged GET of the first 16 bytes without any credentials -> (ok, detail)"""
    req = urllib.request.Request(url, headers={'Range': 'bytes=0-15'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            total = None
            cr = r.headers.get('Content-Range')          # 'bytes 0-15/12345'
            if cr and '/' in cr:
                total = int(cr.rsplit('/', 1)[1])
            ok = r.status in (200, 206) and len(body) > 0 and (want_bytes is None or total in (None, want_bytes))
            return ok, f'http {r.status} got {len(body)} B total {total}'
    except urllib.error.HTTPError as e:
        return False, f'http {e.code}'
    except Exception as e:                               # network errors are failures, never ignored
        return False, f'{type(e).__name__}: {e}'[:200]


def main():
    ap = argparse.ArgumentParser(description='job rows -> pre-signed GET URLs (7 days max)')
    ap.add_argument('--jobs', required=True, help='jobs file (.jsonl or .jsonl.gz): new5.jsonl, jobs_partial.jsonl.gz ...')
    ap.add_argument('--ids', help='comma-separated model ids (default: every job in the file)')
    ap.add_argument('--tags', help='comma-separated tags (new5.jsonl rows carry a tag)')
    ap.add_argument('--expires', type=int, default=MAX_EXPIRES, help='seconds, <= 604800')
    ap.add_argument('--detail', choices=('shipped', 'all', 'none'), default='shipped')
    ap.add_argument('--png', action='store_true', help='also sign the render PNG')
    ap.add_argument('--check', action='store_true', help='HEAD every key: size/ETag must equal the job row')
    ap.add_argument('--allow-changed', action='store_true', help='sign even when --check finds a changed/missing object')
    ap.add_argument('--test', action='store_true', help='ranged GET of every URL (16 bytes, no credentials)')
    ap.add_argument('--allow-session-creds', action='store_true')
    ap.add_argument('--out', required=True, help='URL file (JSON, written 0600)')
    ap.add_argument('--embed-out', help='also write the job rows with a "urls" field ({name: url}) (.jsonl, 0600)')
    ap.add_argument('--workers', type=int, default=16)
    a = ap.parse_args()
    if not 0 < a.expires <= MAX_EXPIRES:
        raise SystemExit(f'--expires must be 1..{MAX_EXPIRES}')
    kind = credential_kind()
    if kind != 'long_term_access_key' and not a.allow_session_creds:
        raise SystemExit('presign.py: temporary credentials: URLs would expire with the session, not after --expires '
                         '(use AWS_PROFILE=bim, or pass --allow-session-creds knowingly)')
    jobs = read_jobs(a.jobs)
    if a.ids:
        want = set(a.ids.split(','))
        jobs = [j for j in jobs if j['model_id'] in want]
        miss = want - {j['model_id'] for j in jobs}
        if miss:
            raise SystemExit(f'presign.py: ids not in {a.jobs}: {sorted(miss)}')
    if a.tags:
        want = set(a.tags.split(','))
        jobs = [j for j in jobs if j.get('tag') in want]
        miss = want - {j.get('tag') for j in jobs}
        if miss:
            raise SystemExit(f'presign.py: tags not in {a.jobs}: {sorted(miss)}')
    t0 = time.time()
    res = s3cache.pmap(lambda j: presign_job(j, a.expires, a.detail, a.png, a.check), jobs, workers=a.workers)
    bad_check = {r['model_id']: {n: v for n, v in r['check'].items() if v != 'ok'} for r in res}
    bad_check = {k: v for k, v in bad_check.items() if v}
    if a.test:
        flat = [(r, n, u) for r in res for n, u in r['urls'].items()]
        outs = s3cache.pmap(lambda x: test_url(x[2]['url'], x[2].get('bytes')), flat, workers=a.workers)
        for (r, n, u), (ok, det) in zip(flat, outs):
            r.setdefault('test', {})[n] = {'ok': ok, 'detail': det}
    bad_test = {r['model_id']: {n: v['detail'] for n, v in r.get('test', {}).items() if not v['ok']} for r in res}
    bad_test = {k: v for k, v in bad_test.items() if v}
    keep = [r for r in res if a.allow_changed or r['model_id'] not in bad_check]
    doc = {'presign_v': PRESIGN_V, 'bucket': s3cache.BUCKET, 'region': s3cache.REGION,
           'profile': os.environ.get('AWS_PROFILE', 'bim'), 'credential_kind': kind, 'jobs_file': os.path.abspath(a.jobs),
           'detail': a.detail, 'n_jobs': len(keep), 'jobs': {r['model_id']: r for r in keep},
           'check_failures': bad_check, 'test_failures': bad_test}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    fd = os.open(a.out + '.tmp', os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(doc, f, indent=1)
    os.replace(a.out + '.tmp', a.out)
    if a.embed_out:
        byid = {r['model_id']: r for r in keep}
        fd = os.open(a.embed_out + '.tmp', os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as f:
            for j in jobs:
                if j['model_id'] in byid:
                    r = byid[j['model_id']]
                    f.write(json.dumps(dict(j, urls={n: u['url'] for n, u in r['urls'].items()},
                                            urls_expire_at=r['expires_at']), ensure_ascii=False) + '\n')
        os.replace(a.embed_out + '.tmp', a.embed_out)
    n_urls = sum(len(r['urls']) for r in keep)
    summary = {'jobs': len(jobs), 'signed_jobs': len(keep), 'urls': n_urls,
               'expires_at': min((r['expires_at'] for r in keep), default=None), 'credential_kind': kind,
               'check_failures': bad_check, 'test_failures': bad_test,
               'tested_ok': sum(1 for r in keep for v in r.get('test', {}).values() if v['ok']) if a.test else None,
               'per_job': {r.get('model_id')[:12]: sorted(r['urls']) for r in keep} if len(keep) <= 10 else None,
               'out': os.path.abspath(a.out), 'sec': round(time.time() - t0, 1)}
    print(json.dumps(summary, indent=1))           # no URL is printed
    if bad_check and not a.allow_changed:
        sys.exit(2)
    if bad_test:
        sys.exit(3)


if __name__ == '__main__':
    main()
