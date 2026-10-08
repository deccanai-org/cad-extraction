import boto3, json, gzip, collections
s3 = boto3.Session(profile_name='bim').client('s3', region_name='ap-south-1')
B = 'bim-proprietary-data'; ST = 'cad-disk-extract/zenitude-data-3/_state'
S = json.loads(s3.get_object(Bucket=B, Key=ST + '/conv/index_summary.json')['Body'].read())
print('updated', S['updated'], 'final', S.get('final'), 'models', S.get('models'))
for p, d in S['pipelines'].items():
    print(f"== {p}: models {d['models']} by_class {d['by_class']} corpus {d['by_class_corpus']}")
    print('   status', d['by_status'], 'reused', d['reused'], d.get('reused_by_source'), 'new_conversions', d['new_conversions'])
    print('   class3 top', dict(list(d['class3_reasons'].items())[:8]))
    print('   class2 issues top', dict(list(d['class2_issues'].items())[:8]))
    print('   standins top', dict(list(d['standin_models_by_type'].items())[:8]))
boots = [o['Key'].rsplit('/', 1)[-1] for pg in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=ST + '/conv/') for o in pg.get('Contents', []) if '/boot/' in o['Key'] and o['Key'].endswith('.txt') and not o['Key'].endswith('.done.txt')]
hosts = sorted({b.split('.')[0] for b in boots})
print('machines (boot records)', len(hosts))
