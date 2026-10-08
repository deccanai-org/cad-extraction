"""splitcmp.py ID12 : per-product solid counts / volumes in the STEP read-back of kit_jg vs kit_jp (step_check --parts output), by root index"""
import json, gzip, sys, collections
i12 = sys.argv[1]
def load(k):
    return [json.loads(l) for l in gzip.open(f'full/{k}/{i12}/step_parts.jsonl.gz', 'rt')]
g, p = load('kit_jg'), load('kit_jp')
print('roots', len(g), len(p), 'solids', sum(r.get('solids', 0) for r in g), sum(r.get('solids', 0) for r in p))
same_names = sum(1 for a, b in zip(g, p) if a.get('name') == b.get('name')); print('same name by index', same_names)
ch = [(a, b) for a, b in zip(g, p) if a.get('solids') != b.get('solids')]
print('roots whose solid count changed', len(ch), 'solids delta', sum(b.get('solids', 0) - a.get('solids', 0) for a, b in ch))
names = collections.Counter((str(a.get('name'))[:70], a.get('solids'), b.get('solids')) for a, b in ch)
for (n, x, y), c in names.most_common(12): print(c, repr(n), x, '->', y)
for a, b in ch[:3]: print(json.dumps(a)[:400]); print(json.dumps(b)[:400])
vch = [(a, b) for a, b in zip(g, p) if a.get('volume') and b.get('volume') and abs(a['volume'] - b['volume']) > 1e-6 * max(1, abs(a['volume']))]
print('roots whose volume changed', len(vch))
