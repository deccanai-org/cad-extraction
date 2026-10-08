import json, os, subprocess, sys, concurrent.futures as cf
M = json.load(open('models.json'))
want = [m for m in M if str(m['engine']) in ('6.87', '7.01', '7.24', '7.30', '7.64', '8.53')]
def get(m):
    p = f"db1/{m['id']}.db1"
    if os.path.exists(p) and os.path.getsize(p) == m['size']:
        return m['id'][:12], 'cached'
    r = subprocess.run(['aws', 's3', 'cp', '--quiet', f"s3://bim-proprietary-data/{m['input_key']}", p], env=dict(os.environ, AWS_PROFILE='bim'), capture_output=True, text=True)
    return m['id'][:12], r.returncode, (r.stderr or '')[-200:]
with cf.ThreadPoolExecutor(8) as ex:
    for x in ex.map(get, want):
        print(x, flush=True)
