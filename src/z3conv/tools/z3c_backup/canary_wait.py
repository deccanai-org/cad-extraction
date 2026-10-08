import boto3, json, time, sys
s3 = boto3.Session(profile_name='bim').client('s3', region_name='ap-south-1')
B = 'bim-proprietary-data'; P = 'cad-disk-extract/zenitude-data-3/_state/conv/sds2/results/'
ids = open('/tmp/z3c/canary/ids.txt').read().split(',')
t0 = time.time()
while True:
    st = {}
    for i in ids:
        try:
            r = json.loads(s3.get_object(Bucket=B, Key=P + i + '.json')['Body'].read())
            alt = r.get('alternatives') or {}
            st[i] = (r.get('code'), r.get('chosen'), sorted(alt.keys()))
        except Exception:
            st[i] = None
    rc_done = [i for i, v in st.items() if v and ('rc' in str(v[0]) or 'v5.5.10-rc' in v[2] or v[1] == 'v5.5.10-rc')]
    if len(rc_done) == len(ids) or time.time() - t0 > float(sys.argv[1]):
        print(json.dumps(st, indent=0)); break
    time.sleep(60)
