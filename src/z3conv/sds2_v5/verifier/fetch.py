"""fetch fleet outputs (STEP + csv + manifest) and the SDS2 job folder for given ids (bim, read-only)"""
import sys, os, json, subprocess, boto3
s3 = boto3.Session(profile_name='bim').client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'
R = {r['id'][:8]: r for r in json.load(open('fleet_index.json')) if r.get('id')}
F = 'cad-disk-extract/zenitude-data-3/_state/conv/sds2/files/'
for i in sys.argv[1:]:
    r = R[i]; od = f'out/{i}'; os.makedirs(od, exist_ok=True)
    for f in r['files']:
        if f.endswith('.png'): continue
        p = os.path.join(od, f)
        if not os.path.exists(p): s3.download_file(B, r['prefix'] + f, p)
    if not os.path.isdir(f'jobs/{i}'):
        k = s3.list_objects_v2(Bucket=B, Prefix=F + r['id'])['Contents'][0]['Key']
        subprocess.run([sys.executable, '../scratch/getjob3k.py', k, 'jobs', i], check=True, stdout=subprocess.DEVNULL)
    print(i, 'ok', sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(f'jobs/{i}') for f in fs) // 1000000, 'MB job')
