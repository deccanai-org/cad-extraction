import boto3, json, sys
s3 = boto3.Session(profile_name='bim').client('s3', region_name='ap-south-1')
B = 'bim-proprietary-data'; OUT = 'cad-disk-extract/zenitude-data-3/conversions/sds2-step'
ids = ["f3482a0d55594d8d8577f98e", "e222e6b62af206b310e8619f", "c053564dec23e0c71d377145", "6eeedc274302b8e4032f8736", "ca1a958a22bc30a35f27fc9d", "8d3cfac8177298d9668c4d18", "1f9bb631e04fa832f5deeca2", "03393338dc50fbc9a4fac87d", "713dae630deda8bf19c3fcf8", "8f39034be367d8255e4eb851", "0535bdbbe63db0f7008b7218", "4c381a54360ac7d2dc367923", "80ea451b800dfd5c56c78d36", "1b6216e02bf7b37dd56f7eb3", "a1a87e6b121b4ddaab6b855a"]
def man(i, lab):
    L = s3.list_objects_v2(Bucket=B, Prefix=f'{OUT}/{i}/{lab}/').get('Contents', [])
    k = [o['Key'] for o in L if o['Key'].endswith('_manifest.json')]
    k.sort(key=lambda x: ('stage2' not in x, x))
    if not k: return None
    m = json.loads(s3.get_object(Bucket=B, Key=k[0])['Body'].read()); m['_key'] = k[0].rsplit('/', 1)[-1]; return m
def summ(m):
    if not m: return None
    c = m.get('counts') or {}; rb = m.get('readback') or {}
    return {'class': m.get('class'), 'corpus': m.get('corpus'), 'solids': c.get('solids_written'), 'pieces': c.get('pieces_written'), 'exact': c.get('pieces_exact'),
            'dup': c.get('duplicate_placements'), 'src_dup': c.get('source_duplicate_placements'), 'conv_dup_skipped': c.get('converter_duplicates_skipped'),
            'skipped': c.get('pieces_skipped') or c.get('skipped'), 'rb': f"{rb.get('valid')}/{rb.get('solids')}", 'reasons': (m.get('class_reasons') or [])[:3],
            'ratio': (m.get('weight_check') or {}).get('ratio'), 'ratio_wo': (m.get('weight_check') or {}).get('ratio_without_outliers'),
            'lists': {k: (len(v) if isinstance(v, (list, dict)) else v) for k, v in m.items() if any(x in k for x in ('dup', 'twin', 'removed', 'stock'))},
            'f': m['_key'][-30:]}
for i in ids:
    b = man(i, 'v5.5.11-rc4')
    if not b: print('==', i[:8], 'rc4 pending'); continue
    a = man(i, 'v5.5.9b') or man(i, 'v5.5.9')
    print('==', i[:8]); print('  base', json.dumps(summ(a))[:420]); print('  rc4 ', json.dumps(summ(b))[:420])
