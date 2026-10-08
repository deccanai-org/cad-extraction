#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
/opt/conv/env/bin/python - <<'PY'
import json, gzip, boto3, collections
s3 = boto3.client('s3'); B = 'bim-proprietary-data'; P = 'cad-disk-extract/_state/packaging/plans/'
miss = json.load(open('/opt/pkgd4/missing_files.json'))
byp = collections.defaultdict(set)
for m in miss: byp[m['project_id']].add(m['relpath'])
out = []; nf = 0
for pid, rels in byp.items():
    objs = s3.list_objects_v2(Bucket=B, Prefix=f'{P}{pid}/').get('Contents') or []
    found = {}
    for o in sorted(objs, key=lambda o: o['LastModified'], reverse=True):
        b = s3.get_object(Bucket=B, Key=o['Key'])['Body'].read()
        if b[:2] == b'\x1f\x8b': b = gzip.decompress(b)
        plan = json.loads(b)
        for it in plan.get('items') or []:
            if it.get('relpath') in rels and it['relpath'] not in found:
                found[it['relpath']] = it
        if len(found) == len(rels): break
    # still missing in the package now?
    man = s3.get_object(Bucket=B, Key=f'cad-disk-extract/dataset/packages/3d/{pid}/manifest.jsonl')['Body'].read().decode('utf-8', 'surrogateescape').split('\n')
    have = {json.loads(l)['relpath'] for l in man if l.strip()}
    for r in rels:
        it = found.get(r)
        if not it: nf += 1; continue
        out.append({'project_id': pid, 'relpath': r, 'path': it.get('source_path'), 'sha256': it.get('sha256'), 'bytes': it.get('bytes'),
                    'src_key': it.get('src_key'), 'in_manifest_now': r in have})
json.dump(out, open('/opt/pkgd4r4/nosuchkey_items.json', 'w'))
print('RESULT items', len(out), 'not in any plan', nf, 'in manifest now', sum(1 for x in out if x['in_manifest_now']))
print('RESULT example', json.dumps(out[0])[:500] if out else None)
print('RESULT src_key prefixes', collections.Counter((x['src_key'] or '')[:45] for x in out).most_common(4))
PY
