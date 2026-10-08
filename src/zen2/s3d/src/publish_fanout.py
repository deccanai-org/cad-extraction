"""Publish IFC chunks + conversion worker for fan-out.

publish_fanout.py  -> s3 sync OUT/ifc -> model/ifc ; jobs.json + worker code -> _control/s3d3d/ ; WORK/fanout.json
"""
import os, sys, json, glob, subprocess, collections
from common import *

CTL = 'cad-disk-extract/zenitude-data-2/_control/s3d3d'


def main():
    final = '--final' in sys.argv
    test = '--test' in sys.argv
    r = subprocess.run(['aws', 's3', 'sync', '--only-show-errors', '--exclude', '*.tmp*', os.path.join(OUT, 'ifc') + '/', 's3://%s/%s/ifc/' % (S3_BUCKET, S3_PREFIX)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print('sync error', r.stderr[-500:]); sys.exit(1)
    jobs = []; by_area = collections.defaultdict(list)
    for f in sorted(glob.glob(os.path.join(WORK, 'ifcdone', '*.json'))):
        m = json.load(open(f))
        asafe = m['ifc'].split('/')[1]
        jobs.append({'id': m['id'], 'kind': m['kind'], 'area': m['area'], 'area_safe': asafe,
                     'input_key': '%s/%s' % (S3_PREFIX, m['ifc']), 'est_size': m['bytes'], 'elements': m['elements'], 'origin': m['origin']})
        by_area[(m['area'], asafe)].append(m['id'])
    jobs.sort(key=lambda j: -j['est_size'])
    for (area, asafe), ids in sorted(by_area.items()):
        jobs.append({'id': 'area__' + asafe, 'kind': 'area_png', 'area': area, 'area_safe': asafe, 'deps': sorted(ids),
                     'est_size': 0, 'input_key': None})
    import boto3
    s3 = boto3.client('s3')
    for fn in ('worker.py', 'setup.sh', 'run.sh', 'requirements.txt', 'ifc2step5.py', 'validate_step.py', 'render.py'):
        s3.upload_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fanout', fn), S3_BUCKET, '%s/%s' % (CTL, fn))
    if test:
        pick = []
        for kind in ('piping', 'structure', 'equipment'):
            c = sorted([j for j in jobs if j['kind'] == kind], key=lambda j: j['est_size'])
            if c:
                pick.append(c[len(c) // 3])
        s3.put_object(Bucket=S3_BUCKET, Key=CTL + '/jobs_test.json', Body=json.dumps(pick).encode(), ContentType='application/json')
        print('test jobs', [(j['id'], j['est_size']) for j in pick]); return
    s3.put_object(Bucket=S3_BUCKET, Key=CTL + '/jobs.json', Body=json.dumps(jobs).encode(), ContentType='application/json')
    if final:
        s3.delete_object(Bucket=S3_BUCKET, Key=CTL + '/publishing')
    else:
        s3.put_object(Bucket=S3_BUCKET, Key=CTL + '/publishing', Body=b'IFC generation still running; jobs.json will grow')
    info = {'fanout_ready': bool(os.path.exists(os.path.join(WORK, 'fanout_proven.json'))), 'job_list_final': final, 'published': utcnow(), 'jobs': len(jobs), 'chunk_jobs': sum(1 for j in jobs if j['kind'] != 'area_png'),
            'area_png_jobs': sum(1 for j in jobs if j['kind'] == 'area_png'), 'ifc_bytes': sum(j['est_size'] for j in jobs),
            'jobs_key': 's3://%s/%s/jobs.json' % (S3_BUCKET, CTL), 'run': 'aws s3 cp s3://%s/%s/run.sh /tmp/run.sh && bash /tmp/run.sh [SLOTS]' % (S3_BUCKET, CTL),
            'claims': 's3://%s/cad-disk-extract/zenitude-data-2/_state/s3d3d/claims/<id>.json (PutObject IfNoneMatch=*)' % S3_BUCKET,
            'results': 's3://%s/cad-disk-extract/zenitude-data-2/_state/s3d3d/results/<id>.json' % S3_BUCKET}
    json.dump(info, open(os.path.join(WORK, 'fanout.json'), 'w'), indent=1)
    print(json.dumps(info, indent=1))


if __name__ == '__main__':
    main()
