#!/usr/bin/env python3
"""publish_partial.py - live, anonymous stats of the partial-tier Modal pipeline -> dhigdec/cad-extract-status partial.json
(public repo: numbers only - no package/project/client names, model ids, bucket paths, URLs).
Run: caffeinate -i python3 publish_partial.py [interval_s]   (default 300; 0 = one round)"""
import json, os, subprocess, sys, time, gzip
import boto3
ROOT = '/Users/dhiren/Downloads/Deccan/partial_modal'
REPO = '/Users/dhiren/Downloads/Deccan/cad-extract-status'
B = 'bim-proprietary-data'
s3 = boto3.Session(profile_name='bim').client('s3', region_name='ap-south-1')

def count(prefix, suffix=''):
    n = 0
    for pg in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=prefix):
        n += sum(1 for o in pg.get('Contents', []) if o['Key'].endswith(suffix))
    return n

def build():
    st = json.load(open(f'{ROOT}/jobs/jobs_stats.json'))
    tier = {src: {cls: v['models'] for cls, v in d.items()} for src, d in st['source_x_class'].items()}
    tb = {src: round(d['ALL']['step_bytes'] / 1e12, 2) for src, d in st['source_x_class'].items() if 'ALL' in d}
    tests = []
    jobs = [json.loads(l) for l in open(f'{ROOT}/jobs/new5.jsonl')]
    pub_total = 0
    for i, j in enumerate(jobs, 1):
        pid = j['pid']
        try:
            n = count(f'cad-disk-extract/dataset/packages/3d_partial/{pid}/scripts/')
        except Exception:
            n = 0
        folder = j.get('model_folder', '')
        mine = count(f'cad-disk-extract/dataset/packages/3d_partial/{pid}/scripts/{folder}/') if folder and n else 0
        coloured = count(f'cad-disk-extract/dataset/packages/3d_partial/{pid}/scripts/{folder}/issues/', '.step') if mine else 0
        pub_total += bool(mine)
        tests.append({'n': f'n{i}', 'source': j.get('step_source'), 'size_mb': round(j.get('bytes', 0) / 1e6),
                      'published_files': mine, 'coloured_steps': coloured, 'state': 'published' if mine else 'running'})
    bundles = count('cad-disk-extract/_state/pmp/bundles/', '.tar.gz')
    rep = os.path.exists(f'{ROOT}/testB_results/REPORT.md')
    return {'updated': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'models': st['models'],
            'packages': st['packages']['listed_under_3d_partial'], 'tier': tier, 'tb': tb,
            'in_scope': sum(v for d in tier.values() for c, v in d.items() if c in ('S', 'M', 'L', 'XL')),
            'tests': tests, 'tests_published': pub_total, 'bundles': bundles, 'report_ready': rep,
            'workstreams': json.load(open(f'{ROOT}/status/workstreams.json'))}

def push(d):
    json.dump(d, open(f'{REPO}/partial.json', 'w'), indent=1)
    subprocess.run(['git', '-C', REPO, 'pull', '-q', '--rebase', '--autostash'], check=False)
    subprocess.run(['git', '-C', REPO, 'add', 'partial.json', 'partial.html'], check=False)
    if subprocess.run(['git', '-C', REPO, 'diff', '--cached', '--quiet']).returncode:
        subprocess.run(['git', '-C', REPO, 'commit', '-qm', 'partial status'], check=False)
        subprocess.run(['git', '-C', REPO, 'push', '-q'], check=False)

iv = int(sys.argv[1]) if len(sys.argv) > 1 else 300
while True:
    try:
        push(build())
    except Exception as e:
        print(time.strftime('%H:%M:%S'), 'error', repr(e), flush=True)
    if not iv: break
    time.sleep(iv)
