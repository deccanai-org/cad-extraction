#!/usr/bin/env python3
"""make_test_jobs.py [--tags n1,n2] [--hours 48]  (Mac; AWS_PROFILE=bim read-only IAM user; no compute)

src_db1 unit-test jobs for the NEW sample models only: rows of jobs/new5.jsonl (the jobs component) + a 'urls' dict of
pre-signed GET URLs for exactly the objects the stage reads:
  db1 (source.key: the package DB1, add-ons: the 3d package's DB1), step (step.key: the delivered package STEP),
  results_json / src_parts / decoded_parts (detail_keys: the conversion fleet's result JSON, per-product census of its IFC,
  decoder parts list).
Writes src_db1/tests/jobs_n1n2.urls.json (mode 0600). The URLs are bearer tokens until they expire: the file is never
printed, never copied into outputs (the stage logs bucket/key only)."""
import argparse, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUCKET = 'bim-proprietary-data'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tags', default='n1,n2')
    ap.add_argument('--hours', type=int, default=48)
    ap.add_argument('--out', default=os.path.join(HERE, 'tests', 'jobs_n1n2.urls.json'))
    a = ap.parse_args()
    import boto3
    s3 = boto3.session.Session(profile_name=os.environ.get('AWS_PROFILE', 'bim'), region_name='ap-south-1').client('s3')
    allowed = {r['model_id'] for r in json.load(open(os.path.join(ROOT, 'new5.json')))}
    rows = [json.loads(l) for l in open(os.path.join(ROOT, 'jobs', 'new5.jsonl'))]
    want = a.tags.split(',')
    out = []
    for r in rows:
        if not any(r['tag'].startswith(t) for t in want) or r['step_source'] != 'db1':
            continue
        assert r['model_id'] in allowed
        keys = {'db1': r['source']['key'], 'step': r['step']['key']}
        for k in ('results_json', 'src_parts', 'decoded_parts'):
            if (r.get('detail_keys') or {}).get(k):
                keys[k] = r['detail_keys'][k]
        urls = {}
        for k, key in keys.items():
            s3.head_object(Bucket=BUCKET, Key=key)            # exists + readable (read-only call)
            urls[k] = s3.generate_presigned_url('get_object', Params={'Bucket': BUCKET, 'Key': key}, ExpiresIn=a.hours * 3600)
        out.append(dict(r, urls=urls))
        print(r['tag'], r['model_id'][:16], 'urls for', sorted(urls))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    fd = os.open(a.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(out, f, indent=1)
    print('wrote', a.out, len(out), 'jobs (URLs not shown)')


if __name__ == '__main__':
    main()
