#!/usr/bin/env python3
"""Build the src_sds2 unit-test job for ONE new sample (default n5_sds2) on the Mac: package manifest row (read-only S3,
AWS_PROFILE=bim, cached by jobs/s3cache.py), converter pin (pin.py, with the fleet's result JSON as cross-check) and
pre-signed GET URLs (read-only IAM user, 24 h). The job file holds bearer URLs: write it to a scratch path, never into the
repo, never publish it. Only the new samples of new5.json are accepted (the original 5 samples are never run on Modal).
usage: make_test_job.py OUT_JOB.json [--tag n5_sds2] [--expires 86400]"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
ROOT = os.path.dirname(SRC)
sys.path.insert(0, SRC)
sys.path.insert(0, os.path.join(ROOT, 'jobs'))
import pin as PIN  # noqa: E402
import s3cache  # noqa: E402

B = 'bim-proprietary-data'
PKG = 'cad-disk-extract/dataset/packages/3d_partial/'
args = sys.argv[1:]
outp = args[0]
tag = args[args.index('--tag') + 1] if '--tag' in args else 'n5_sds2'
exp = int(args[args.index('--expires') + 1]) if '--expires' in args else 86400
new5 = {r['tag']: r for r in json.load(open(os.path.join(ROOT, 'new5.json')))}
if tag not in new5:
    raise SystemExit(f'{tag} is not one of the new samples {sorted(new5)}')
s = new5[tag]
if s['step_source'] != 'sds2':
    raise SystemExit(f'{tag} is not an SDS/2 model')
man = s3cache.get_text(PKG + s['pid'] + '/manifest.jsonl', 'man_partial')
rows = [json.loads(l) for l in man.splitlines() if l.strip()]
row = next(r for r in rows if r.get('model_id') == s['model_id'] and r['relpath'] == s['relpath'])
src = next(r for r in rows if r['relpath'] == row['converted_from'])
disk = 'zentitude-data-4' if s['pid'].startswith('Zentitude-data-4') else 'zenitude-data-3'
res_key = f'cad-disk-extract/{disk}/_state/conv/sds2/results/{s["model_id"]}.json'
res_txt = s3cache.get_text(res_key, 'sds2_results')
res = json.loads(res_txt) if res_txt else None
pin = PIN.resolve_pin(row, res)
c = s3cache.client()


def url(key):
    return c.generate_presigned_url('get_object', Params={'Bucket': B, 'Key': key}, ExpiresIn=exp)


job = dict(id=s['model_id'], model_id=s['model_id'], tag=tag, pid=s['pid'], relpath=row['relpath'],
           bytes=row['bytes'], step_sha256=row['sha256'], step_key=row.get('step_key'), source_key=row.get('source_key'),
           converted_from=row['converted_from'], sds2_bytes=src['bytes'], sds2_sha256=src['sha256'],
           converter=row.get('converter'), converter_pin=pin, partial=row.get('partial'), grader=row.get('grader'),
           step_source='sds2', source_kind='emitted_from_sds2',
           urls=dict(step=url(PKG + s['pid'] + '/' + row['relpath']), sds2=url(PKG + s['pid'] + '/' + row['converted_from'])))
os.makedirs(os.path.dirname(os.path.abspath(outp)), exist_ok=True)
with open(outp, 'w') as f:
    json.dump(job, f, indent=1)
red = {k: v for k, v in job.items() if k != 'urls'}
print(json.dumps(dict(red, urls=sorted(job['urls'])), indent=1)[:3000])
