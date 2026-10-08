"""verify_z4_final.py - end-of-run verification for Zentitude-data-4 (read-only). Checks:
 1. every job in jobs.json has a result; status counts; every non-ok result with its 7-Zip reason
 2. completeness vs the drive report (per-archive top-level file counts, from the in-region stats)
 3. every source object (archives + loose files) is present in zentitude-data-4/source/ with the same size
 4. every job that ever had an error record has a result now
 5. nesting depth, password-locked nested archives, ransomware-flagged files, zero-byte files, upload errors
Writes the summary to _state/final_verify.json and prints it.
"""
import json, collections, time
from concurrent.futures import ThreadPoolExecutor
import boto3

ses = boto3.Session(profile_name='bim')
s3 = ses.client('s3', region_name='ap-south-1')
B, R = 'annotationprod', 'cad-disk-extract/zentitude-data-4'


def lst(bucket, prefix):
    out, tok = [], None
    while True:
        kw = dict(Bucket=bucket, Prefix=prefix)
        if tok:
            kw['ContinuationToken'] = tok
        r = s3.list_objects_v2(**kw)
        out += r.get('Contents', [])
        if not r.get('IsTruncated'):
            return out
        tok = r['NextContinuationToken']


def gj(key):
    return json.loads(s3.get_object(Bucket=B, Key=key)['Body'].read())


jobs = gj(f'{R}/_control/jobs.json')
res_objs = [o for o in lst(B, f'{R}/_state/results/') if o['Key'].endswith('.json')]
with ThreadPoolExecutor(48) as ex:
    results = {r['id']: r for r in ex.map(lambda o: gj(o['Key']), res_objs)}
missing = [j for j in jobs if j['id'] not in results]
status = collections.Counter(r['status'] for r in results.values())
non_ok = [{'id': r['id'], 'status': r['status'], 'extract_rc': r.get('extract_rc'), 'files': r['files'],
           'reason': (r.get('extract_stderr') or '').strip().splitlines()[-1:] or [e.get('stderr', '').strip()[-160:] for e in r.get('nested_errors', [])[:2]],
           'nested_errors': len(r.get('nested_errors', [])), 'upload_errors': r.get('upload_error_count', 0)}
          for r in results.values() if r['status'] != 'ok']
ext = gj(f'{R}/_state/stats/ext_summary.json')

# 3. source copy completeness
src = {o['Key'][len('Zentitude-data-4/'):]: o['Size'] for o in lst('bim-proprietary-data', 'Zentitude-data-4/') if not (o['Key'].endswith('/') and o['Size'] == 0)}
dst = {o['Key'][len(f'{R}/source/'):]: o['Size'] for o in lst(B, f'{R}/source/')}
src_missing = [k for k in src if k not in dst]
src_size_diff = [k for k in src if k in dst and dst[k] != src[k]]

# 4. error records resolved?
err_ids = {o['Key'].rsplit('/', 1)[-1].split('.')[0] for o in lst(B, f'{R}/_state/errors/')}
err_unresolved = sorted(i for i in err_ids if i not in results)

rs = list(results.values())
summary = {
    'checked_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    'jobs': len(jobs), 'results': len(results), 'missing_results': [j['key'] for j in missing],
    'status': dict(status), 'non_ok': non_ok,
    'completeness_vs_drive_report': ext.get('verify'), 'archives_counted_in_stats': ext.get('archives_counted'),
    'source_objects_on_drive': len(src), 'source_objects_copied': len(dst), 'source_missing': src_missing[:50],
    'source_missing_count': len(src_missing), 'source_size_mismatch': src_size_diff[:50],
    'error_records': len(err_ids), 'error_jobs_still_without_result': err_unresolved,
    'totals': {k: sum(r.get(k, 0) or 0 for r in rs) for k in ('files', 'bytes', 'stored_files', 'stored_bytes', 'dedup_files',
                                                           'already_in_disk12_files', 'nested_count', 'encrypted_nested',
                                                           'ransomware_files', 'zero_byte_files', 'upload_error_count')},
    'max_nested_depth': ext.get('max_nested_depth'), 'distinct_extensions': ext.get('distinct_extensions'),
}
s3.put_object(Bucket=B, Key=f'{R}/_state/final_verify.json', Body=json.dumps(summary, indent=1).encode(), ContentType='application/json')
print(json.dumps({k: v for k, v in summary.items() if k != 'non_ok'}, indent=1))
print('non-ok archives:', len(non_ok))
for x in non_ok[:60]:
    print(' ', x['status'], 'rc', x['extract_rc'], 'files', x['files'], 'nested_err', x['nested_errors'], 'upload_err', x['upload_errors'], '|', str(x['reason'])[:150])
