import json, os, subprocess, collections, re
J = json.load(open('../work/d3jobs.json'))
raw = [l.rstrip('\n').split(None, 3) for l in open('kwik_raw.lst')]
raw = [(int(p[2]), p[3]) for p in raw if len(p) == 4]
out = {}
for j in J:
    k = j['input_key']; d = os.path.dirname(k) + '/'
    if k.startswith('Zenitude-data-3/'):
        files = [(s, key) for s, key in raw if key.startswith(d) and '/' not in key[len(d):]]
    else:
        r = subprocess.run(['aws', 's3', 'ls', f's3://bim-proprietary-data/{d}'], capture_output=True, text=True, env=dict(os.environ, AWS_PROFILE='bim'))
        files = []
        for l in r.stdout.splitlines():
            p = l.split(None, 3)
            if len(p) == 4 and p[2].isdigit(): files.append((int(p[2]), d + p[3]))
    out[j['sha256']] = dict(dir=d, files=files)
json.dump(out, open('folders.json', 'w'))
c = collections.Counter()
for sha, v in out.items():
    names = [os.path.basename(k).lower() for s, k in v['files']]
    c['profdb'] += any(n == 'profdb.bin' for n in names); c['xsr'] += any(n.endswith('.xsr') for n in names)
    c['xslib'] += any(n == 'xslib.db1' for n in names); c['inp'] += any(n.endswith('.inp') for n in names); c['clb'] += any(n.endswith('.clb') for n in names)
    c['ifc'] += any(n.endswith('.ifc') for n in names)
print(len(out), c)
