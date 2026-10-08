# mkfetch2.py JOBID FPC OUTDIR [lite] -> fetch list (lite: skip subm/<n> piece files)
import sys, json, gzip, os, boto3, re
jid, fpc, outdir = sys.argv[1:4]; lite = len(sys.argv) > 4
s3 = boto3.client('s3', region_name='ap-south-1')
body = s3.get_object(Bucket='bim-proprietary-data', Key=f'cad-disk-extract/zenitude-data-3/_state/conv/sds2/files/{fpc}.json.gz')['Body'].read()
try: body = gzip.decompress(body)
except OSError: pass
mf = json.loads(body)
CANON = {"main", "mem", "subm", "jsetup", "job_mtrl", "mem_idx", "subm_idx"}
items = []
for f in mf:
    parts = [p.lower() if p.lower() in CANON else p for p in f['p'].replace('\\', '/').split('/') if p]
    if lite and len(parts) >= 2 and parts[-2] == 'subm' and parts[-1].isdigit():
        continue
    items.append([f.get('key') or '', os.path.join(outdir, *parts), f['size']])
json.dump(items, open(f'fetch_{jid}.json', 'w'))
print(jid, len(items), sum(i[2] for i in items))
