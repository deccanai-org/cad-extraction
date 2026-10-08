import boto3, json, sys
s3 = boto3.Session(profile_name='bim').client('s3', region_name='ap-south-1')
B = 'bim-proprietary-data'; OUT = 'cad-disk-extract/zenitude-data-3/conversions/sds2-step'
ids = open('/tmp/z3c/canary/ids11.txt').read().split(',')
def man(i, lab):
    L = s3.list_objects_v2(Bucket=B, Prefix=f'{OUT}/{i}/{lab}/').get('Contents', [])
    k = [o['Key'] for o in L if o['Key'].endswith('_stage2_manifest.json')]
    if not k: return None
    return json.loads(s3.get_object(Bucket=B, Key=k[0])['Body'].read())
for i in ids:
    a, b = man(i, 'v5.5.9b'), man(i, 'v5.5.11-rc')
    def summ(m):
        if not m: return None
        c = m.get('counts') or {}; rb = m.get('readback') or {}
        return {'class': m.get('class'), 'corpus': m.get('corpus'), 'solids_written': c.get('solids_written'), 'pieces_written': c.get('pieces_written'),
                'exact': c.get('pieces_exact'), 'rb_solids': rb.get('solids'), 'rb_valid': rb.get('valid'), 'excluded': c.get('invalid_parts_excluded'),
                'repair': {k: (len(v) if isinstance(v, list) else v) for k, v in (m.get('readback_repair') or {}).items()} if m.get('readback_repair') else None,
                'reasons': (m.get('class_reasons') or [])[:2]}
    print('==', i[:10]); print('  v5.5.9b   ', json.dumps(summ(a))[:400]); print('  v5.5.11-rc', json.dumps(summ(b))[:400])
