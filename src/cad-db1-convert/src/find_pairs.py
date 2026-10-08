"""Pick DB1 (unsupported/failed engines) + Tekla-exported IFC from the same folder, per engine."""
import boto3, json, collections, random, concurrent.futures as cf, sys
s = boto3.Session(profile_name=None if (__import__('os').environ.get('AWS_ACCESS_KEY_ID') or __import__('os').environ.get('AWS_PROFILE')) else 'annotationprod-publish').client('s3', region_name='ap-south-1')
B = 'annotationprod'
C = [json.loads(l) for l in s.get_object(Bucket=B, Key='cad-disk-extract/_control/db1-v2/census.jsonl')['Body'].read().decode().splitlines()]
open('census.jsonl', 'w').write('\n'.join(json.dumps(c) for c in C))
C = [c for c in C if c['status'] in ('UNSUPPORTED', 'FAILED') and c['sib_ifc'] > 0 and c['bytes'] > 100_000]
random.seed(7); random.shuffle(C)
by = collections.defaultdict(list)
for c in C: by[(c['status'], c['engine'])].append(c)
def probe(c):
    d = c['source_key'].rsplit('/', 1)[0] + '/'
    out = []
    for o in s.list_objects_v2(Bucket=B, Prefix=d, Delimiter='/').get('Contents', []):
        if o['Key'].lower().endswith('.ifc') and 100_000 < o['Size'] < 80_000_000:
            h = s.get_object(Bucket=B, Key=o['Key'], Range='bytes=0-1500')['Body'].read().decode('latin1')
            if 'Tekla Structures' in h and 'GridExporter' not in h:
                out.append((o['Key'], o['Size']))
    return c, out
pairs = []
with cf.ThreadPoolExecutor(32) as ex:
    for (st, eng), lst in sorted(by.items()):
        got = 0
        for c, out in ex.map(probe, lst[:60]):
            if out and got < 8:
                pairs.append(dict(status=st, engine=eng, sha=c['sha'], db1=c['source_key'], db1_bytes=c['bytes'],
                                  ifc=sorted(out, key=lambda x: -x[1])[0])); got += 1
        print(st, eng, len(lst), 'pairs', got, flush=True)
json.dump(pairs, open('pairs/pairs.json', 'w'), indent=1)
