#!/usr/bin/env python3
"""presign_put.py - runs ON the EC2 box i-0f35da72bf742063d (Mumbai) with its instance role (cad-disk-extract-ec2).

Makes one pre-signed HTTP PUT URL per (run, model_id) for
    s3://bim-proprietary-data/cad-disk-extract/_state/pmp/bundles/<run>/<model_id>.tar.gz
and writes the URL list to
    s3://bim-proprietary-data/cad-disk-extract/_state/pmp/presign/<run>.json
(read back on the Mac with AWS_PROFILE=bim; never printed here: a URL carries a signature + the role's session token).

Expiry: a SigV4 pre-signed URL stops working when the credentials that signed it expire, whatever X-Amz-Expires says.
The role's temporary credentials are read straight from the instance metadata (IMDSv2) so their exact Expiration is
known; X-Amz-Expires = Expiration - now - SAFETY (capped at 7 days). The file records expires_utc; refuse to sign when
fewer than --min-valid-minutes remain (the role rotates its credentials about hourly, each new set valid ~6 h - retry
after the next rotation).

    /opt/pm/venv/bin/python presign_put.py --run RUN (--ids-file F | --model-id ID ...) [--min-valid-minutes 60]
    /opt/pm/venv/bin/python presign_put.py --pairs-file F      # JSON list of [run, model_id] / {"run":..,"model_id":..}, or JSONL

Input files: plain text (one model_id per line), a JSON list, or JSONL rows with model_id (and run). Output: a JSON
summary on stdout (counts, expiry, S3 key of each written URL file) - no URLs.
"""
import argparse
import collections
import datetime as dt
import json
import os
import re
import sys
import urllib.request

import boto3
import botocore.config

BUCKET = 'bim-proprietary-data'
REGION = 'ap-south-1'
BUNDLE_PREFIX = 'cad-disk-extract/_state/pmp/bundles/'
PRESIGN_PREFIX = 'cad-disk-extract/_state/pmp/presign/'
SAFETY = 120                       # seconds kept before the credential expiry
MAX_EXPIRES = 7 * 24 * 3600
RUN_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')
MODEL_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')
IMDS = 'http://169.254.169.254'


def imds(path, token, method='GET', headers=None):
    req = urllib.request.Request(IMDS + path, method=method, headers=headers or {'X-aws-ec2-metadata-token': token})
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.read().decode()


def role_credentials():
    """the instance role's current temporary credentials + their expiry, straight from IMDSv2"""
    token = imds('/latest/api/token', None, method='PUT', headers={'X-aws-ec2-metadata-token-ttl-seconds': '300'})
    role = imds('/latest/meta-data/iam/security-credentials/', token).strip().splitlines()[0]
    d = json.loads(imds('/latest/meta-data/iam/security-credentials/' + role, token))
    if d.get('Code') != 'Success':
        raise SystemExit(f'presign_put.py: instance credentials not available (Code={d.get("Code")})')
    exp = dt.datetime.strptime(d['Expiration'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=dt.timezone.utc)
    return role, d, exp


def read_ids(path):
    raw = open(path, encoding='utf-8').read()
    s = raw.strip()
    out = []
    if s.startswith('['):
        for x in json.loads(s):
            out.append(x if isinstance(x, (list, dict)) else str(x))
    else:
        for ln in s.splitlines():
            ln = ln.strip()
            if not ln or ln.startswith('#'):
                continue
            out.append(json.loads(ln) if ln.startswith('{') else ln)
    return out


def pairs_from(items, default_run):
    pairs = []
    for x in items:
        if isinstance(x, dict):
            run, mid = x.get('run', default_run), x.get('model_id')
        elif isinstance(x, list):
            run, mid = (x[0], x[1]) if len(x) == 2 else (default_run, x[0])
        else:
            run, mid = default_run, x
        pairs.append((run, mid))
    return pairs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--run', help='run name (default for ids without one)')
    ap.add_argument('--model-id', action='append', default=[], help='model id (repeatable)')
    ap.add_argument('--ids-file', help='model ids: text lines / JSON list / JSONL (model_id[, run])')
    ap.add_argument('--pairs-file', help='same as --ids-file; rows carry their own run')
    ap.add_argument('--min-valid-minutes', type=float, default=60.0, help='refuse when the URLs would expire sooner (default 60)')
    ap.add_argument('--expires-seconds', type=int, default=None, help='shorter validity than the credentials allow (optional)')
    a = ap.parse_args()

    items = list(a.model_id)
    for f in (a.ids_file, a.pairs_file):
        if f:
            items += read_ids(f)
    pairs = pairs_from(items, a.run)
    if not pairs:
        raise SystemExit('presign_put.py: no model ids given')
    by_run = collections.OrderedDict()
    for run, mid in pairs:
        if not isinstance(run, str) or not RUN_RE.match(run):
            raise SystemExit(f'presign_put.py: bad or missing run {run!r} (must match {RUN_RE.pattern})')
        if not isinstance(mid, str) or not MODEL_ID_RE.match(mid):
            raise SystemExit(f'presign_put.py: bad model_id {mid!r} (must match {MODEL_ID_RE.pattern})')
        by_run.setdefault(run, [])
        if mid not in by_run[run]:
            by_run[run].append(mid)

    role, cred, exp = role_credentials()
    now = dt.datetime.now(dt.timezone.utc)
    left = int((exp - now).total_seconds()) - SAFETY
    expires = min(left, MAX_EXPIRES, a.expires_seconds or MAX_EXPIRES)
    if expires < a.min_valid_minutes * 60:
        raise SystemExit(f'presign_put.py: the role credentials expire at {exp:%Y-%m-%dT%H:%M:%SZ}, only {left // 60} min left '
                         f'(< --min-valid-minutes {a.min_valid_minutes:g}); retry after the next credential rotation (~hourly)')
    s3 = boto3.client('s3', region_name=REGION, aws_access_key_id=cred['AccessKeyId'], aws_secret_access_key=cred['SecretAccessKey'],
                      aws_session_token=cred['Token'],
                      config=botocore.config.Config(signature_version='s3v4', s3={'addressing_style': 'virtual'},
                                                    retries={'max_attempts': 8, 'mode': 'standard'}))
    host = f'{BUCKET}.s3.{REGION}.amazonaws.com'
    until = now + dt.timedelta(seconds=expires)
    summary = dict(ok=True, role=role, generated_utc=now.strftime('%Y-%m-%dT%H:%M:%SZ'), expires_utc=until.strftime('%Y-%m-%dT%H:%M:%SZ'),
                   credential_expiration_utc=exp.strftime('%Y-%m-%dT%H:%M:%SZ'), expires_in_s=expires, runs={})
    for run, mids in by_run.items():
        urls = collections.OrderedDict()
        for mid in mids:
            key = f'{BUNDLE_PREFIX}{run}/{mid}.tar.gz'
            u = s3.generate_presigned_url('put_object', Params={'Bucket': BUCKET, 'Key': key}, ExpiresIn=expires, HttpMethod='PUT')
            if not u.startswith(f'https://{host}/'):
                raise SystemExit(f'presign_put.py: unexpected endpoint in the signed URL (want the regional host {host})')
            urls[mid] = dict(key=key, url=u)
        doc = dict(format='pmp-presign/1', run=run, bucket=BUCKET, region=REGION, method='PUT',
                   headers_note='plain PUT with Content-Length (Content-Type optional); S3 refuses unsigned Content-MD5 / '
                                'x-amz-* headers on these URLs; check the response ETag == MD5 of the body (bundle_lib.upload_bundle)',
                   generated_utc=summary['generated_utc'], expires_utc=summary['expires_utc'],
                   credential_expiration_utc=summary['credential_expiration_utc'], expires_in_s=expires, n=len(urls), urls=urls)
        out_key = f'{PRESIGN_PREFIX}{run}.json'
        assert out_key.startswith(PRESIGN_PREFIX)
        s3.put_object(Bucket=BUCKET, Key=out_key, Body=json.dumps(doc, indent=1).encode(), ContentType='application/json')
        summary['runs'][run] = dict(n=len(urls), s3=f's3://{BUCKET}/{out_key}', bundle_prefix=f's3://{BUCKET}/{BUNDLE_PREFIX}{run}/')
    print(json.dumps(summary, indent=1))


if __name__ == '__main__':
    sys.exit(main())
