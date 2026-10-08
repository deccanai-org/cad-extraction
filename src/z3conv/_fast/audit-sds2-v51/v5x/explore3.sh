#!/bin/bash
cd /work/agentwork/audit-sds2-v5x
export AWS_DEFAULT_REGION=ap-south-1
echo "== versioning"; aws s3api get-bucket-versioning --bucket bim-proprietary-data 2>&1 | head -5
aws s3api list-object-versions --bucket bim-proprietary-data --prefix cad-disk-extract/zenitude-data-3/_state/conv/sds2/results/ff442ef160919656b2fea194.json --query 'Versions[].[VersionId,LastModified,Size]' --output text 2>&1 | head
/opt/conv/env/bin/python - <<'PY'
import json, glob, re, os, collections
def lab(c):
    m = re.match(r'z3-sds2-(v[\d.]+?)-20\d\d', str(c or '')); return m.group(1) if m else None
def ts(t):
    h, m, s = map(int, t.split(':')); v = h*3600+m*60+s; return v + 86400 if h < 12 else v
P = {}
for f in glob.glob('s3/sds2/logs/*.log'):
    hp = os.path.basename(f)[:-4]; host = hp.rsplit('-', 1)[0]; pid = hp.rsplit('-', 1)[1]
    t = open(f, errors='replace').read(); lines = t.splitlines()
    m = re.search(r'worker code=(\S+)', t); code = lab(m.group(1)) if m else None
    tl = [ts(l[:8]) for l in lines if re.match(r'\d\d:\d\d:\d\d ', l)]
    kills = re.findall(r'^(\d\d:\d\d:\d\d) WATCHDOG killed (\w+) rss=(\d+)GB avail=(\d+)GB(.*)$', t, re.M)
    P[hp] = {'host': host.split('.')[0], 'pid': pid, 'code': code, 'first': min(tl) if tl else None, 'last': max(tl) if tl else None,
             'kills': kills, 'exit': [l for l in lines if 'exiting' in l or 'handed' in l or 'hand-off' in l][-2:]}
H = {}
for f in glob.glob('s3/sds2/hosts/*.json'):
    h = json.load(open(f)); H[os.path.basename(f)[:-5]] = h
# per host: processes alive windows + kills
byhost = collections.defaultdict(list)
for hp, p in P.items(): byhost[p['host']].append((hp, p))
def hm(v): 
    if v is None: return None
    v %= 86400; return '%02d:%02d:%02d' % (v//3600, v%3600//60, v%60)
for host in sorted(byhost):
    ps = sorted(byhost[host], key=lambda x: x[1]['first'] or 0)
    v53 = [k for hp, p in ps if p['code'] == 'v5.3' for k in p['kills']]
    if not v53: continue
    print('#### host', host, 'v5.3 kills', len(v53), 'rss', collections.Counter(int(k[2]) for k in v53).most_common(6))
    for hp, p in ps:
        hb = H.get(hp) or {}
        run = hb.get('running') or []
        print('   pid', p['pid'], p['code'], hm(p['first']), '->', hm(p['last']), 'kills', len(p['kills']), 'kill rss', sorted(int(k[2]) for k in p['kills'])[-6:],
              '| hb', hb.get('at'), 'running', len(run), 'rss_sum', round(sum((x.get('rss') or 0) for x in run)/2**30,1), 'rss_max', round(max([(x.get('rss') or 0) for x in run] or [0])/2**30,1), 'avail', hb.get('mem_avail_gb'), 'handed_off', hb.get('handed_off'))
    # for each v5.3 kill: which other processes were alive (first<=t<=last)
    for hp, p in ps:
        if p['code'] != 'v5.3': continue
        for k in p['kills'][:4]:
            t = ts(k[0]); alive = [(q['pid'], q['code']) for hq, q in ps if hq != hp and q['first'] and q['first'] <= t <= (q['last'] or 0) + 120]
            print('      kill', k[0], k[1], 'rss', k[2], 'avail', k[3], 'alive others:', alive)
PY
