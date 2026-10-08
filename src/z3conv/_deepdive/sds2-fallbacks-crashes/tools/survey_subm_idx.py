"""Read-only survey: subm_idx size divisibility per piece-table slot size vs the job version (jsetup first line).
usage: survey_subm_idx.py <n jobs> <out.jsonl>"""
import sys, json, gzip, re, random, boto3, concurrent.futures as cf
s3 = boto3.Session(profile_name='bim').client('s3', region_name='ap-south-1')
B = 'bim-proprietary-data'
jobs = json.load(open('data/jobs.json'))
random.seed(7); sample = random.sample(jobs, min(int(sys.argv[1]), len(jobs)))
# always include the crash jobs
crash = ('4d8b0b97', '65239fba', '8e970046', 'da281287', 'e18713de', 'e3038e02', 'bf530885')
sample += [j for j in jobs if j['id'].startswith(crash) and j not in sample]
def one(j):
    try:
        b = s3.get_object(Bucket=B, Key=j['files_key'])['Body'].read()
        try: b = gzip.decompress(b)
        except OSError: pass
        fs = {f['p'].replace('\\', '/').lower(): f for f in json.loads(b)}
        si = fs.get('subm/subm_idx'); js = fs.get('main/jsetup')
        ver = None
        if js and js.get('key'):
            h = s3.get_object(Bucket=B, Key=js['key'], Range='bytes=0-63')['Body'].read()
            m = re.match(rb'\s*version\s+([0-9.]+)', h); ver = m.group(1).decode() if m else None
        n = si['size'] if si else None
        div = [S for S in (852, 902, 1024, 440, 384) if n and n >= 256 and (n - 256) % S == 0]
        return dict(id=j['id'], name=j['name'], ver=ver, subm_idx=n, div=div, mem_files=sum(1 for p in fs if p.startswith('mem/') and p[4:].isdigit()))
    except Exception as e:
        return dict(id=j['id'], err=str(e)[:200])
with cf.ThreadPoolExecutor(24) as ex, open(sys.argv[2], 'w') as out:
    for r in ex.map(one, sample):
        out.write(json.dumps(r) + '\n')
