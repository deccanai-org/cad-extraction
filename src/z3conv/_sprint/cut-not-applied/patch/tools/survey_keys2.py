"""survey_keys2.py : rows still without input_key -> Windows-pipeline result.json source_key"""
import json, boto3
s3 = boto3.client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'
A = json.load(open('data/db1_all.json'))
for o in A:
    if o.get('input_key') or not o.get('g_result_key'): continue
    try:
        r = json.loads(s3.get_object(Bucket=B, Key=o['g_result_key'])['Body'].read())
    except Exception as e:
        print('no result', o['id'][:16], e); continue
    o['input_key'] = r.get('source_key'); o['win_result'] = {k: r.get(k) for k in ('qa_verdict', 'status', 'pipeline_manifest', 'reports_downloaded')}
    print(o['id'][:16], o['engine'], (o['input_key'] or 'NONE')[-90:], str(o['win_result'])[:300])
json.dump(A, open('data/db1_all.json', 'w'), indent=0, default=str)
print('with key', sum(1 for o in A if o.get('input_key')), 'of', len(A))
