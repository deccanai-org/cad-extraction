"""bbox_pair_drive.py NAME DIR_A DIR_B : run bbox_pair.py in chunks (subprocesses: a kernel crash on one element loses only its chunk,
which is split down to 25 parts), sum the per-family results"""
import sys, json, subprocess, collections
NAME, DA, DB = sys.argv[1:4]; W = '/work/agentwork/cut-not-applied'
def run(a, b):
    p = subprocess.run(['/opt/conv/env/bin/python', W + '/tools/bbox_pair.py', NAME, DA, DB, str(a), str(b)], capture_output=True, text=True, timeout=7200)
    js = [l for l in p.stdout.splitlines() if l.startswith('{')]
    return json.loads(js[-1]) if p.returncode == 0 and js else None
first = run(0, 1); total = first['total_pairs'] if first else 0
tot = collections.defaultdict(collections.Counter); ex = collections.defaultdict(list); lost = 0; todo = [(i, min(total, i + 3000)) for i in range(0, total, 3000)]
while todo:
    a, b = todo.pop(0); r = run(a, b)
    if r is None:
        if b - a > 25: m = (a + b) // 2; todo[:0] = [(a, m), (m, b)]
        else: lost += b - a
        continue
    for k, v in r['res'].items(): tot[k].update(v)
    for k, v in r['ex'].items(): ex[k] += v
print('==', NAME, 'paired parts written uncut in both runs, joined to Tekla IFC; A =', DA, '| B =', DB, '| pairs', total, '| parts lost to kernel crashes', lost)
for k, v in sorted(tot.items()): print('  %-16s' % k, dict(v), 'worsened e.g.', ex.get(k, [])[:3])
