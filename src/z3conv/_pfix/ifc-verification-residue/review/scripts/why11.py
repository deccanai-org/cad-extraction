# why11.py : parts valid in rvF (fleet grader, in place) but invalid in rvG (second-read) on the same kind of 6.1.4 STEP; inspect their STEP structure
import gzip, json, re, sys, collections
W = '/work/agentwork/ifc-verification-residue-review/w/'
i = sys.argv[1]
def parts(l):
    d = {}
    for line in gzip.open(W + l + '/' + i + '/step_parts.jsonl.gz', 'rt'):
        r = json.loads(line); d[r.get('pid')] = r
    return d
F, G = parts('rvF'), parts('rvG')
bad = [p for p in G if G[p].get('solids') and G[p].get('valid', 0) < G[p]['solids'] and p in F and F[p].get('valid') == F[p].get('solids')]
print('valid in F, invalid in G:', len(bad))
step = W + 'rvG/' + i + '/out.step'
ents = {}
with open(step, encoding='latin-1') as f:
    buf = ''
    for line in f:
        buf += line.strip()
        if buf.endswith(';'):
            m = re.match(r'#(\d+)=(.*);$', buf)
            if m: ents[int(m.group(1))] = m.group(2)
            buf = ''
prod = {}
for k, v in ents.items():
    if v.startswith('PRODUCT('):
        g = re.findall(r"'((?:[^']|'')*)'", v)
        prod[g[0] if g else None] = k
refs = lambda s: [int(x) for x in re.findall(r'#(\d+)', s)]
def closure(root, lim=200000):
    seen = set(); st = [root]
    while st and len(seen) < lim:
        x = st.pop()
        if x in seen or x not in ents: continue
        seen.add(x); st += refs(ents[x])
    return seen
# product -> PDF -> PD -> PDS -> SDR -> shape rep (reverse refs)
rev = collections.defaultdict(list)
for k, v in ents.items():
    for r in refs(v): rev[r].append(k)
def up(k, typ):
    out = []; st = [k]; seen = set()
    while st:
        x = st.pop()
        for y in rev.get(x, []):
            if y in seen: continue
            seen.add(y)
            if ents[y].startswith(typ): out.append(y)
            elif any(ents[y].startswith(t) for t in ('PRODUCT_DEFINITION_FORMATION', 'PRODUCT_DEFINITION(', 'PRODUCT_DEFINITION_SHAPE')): st.append(y)
    return out
for p in bad[:4]:
    k = prod.get(p)
    sdrs = up(k, 'SHAPE_DEFINITION_REPRESENTATION') if k else []
    info = {'pid': p, 'name': G[p].get('name'), 'desc': G[p].get('desc'), 'F_vol': F[p].get('volume'), 'G_vol': G[p].get('volume'), 'solids': G[p]['solids'], 'G_valid': G[p].get('valid')}
    for s in sdrs[:1]:
        cl = closure(s)
        types = collections.Counter(ents[x].split('(')[0] for x in cl)
        pts = [ents[x] for x in cl if ents[x].startswith('CARTESIAN_POINT')]
        far = near = 0; nearex = []
        for x in [x for x in cl if ents[x].startswith('CARTESIAN_POINT')]:
            q = ents[x]
            v = re.search(r"CARTESIAN_POINT\('[^']*',\(([^)]*)\)\)", q)
            if not v: continue
            vals = [float(t) for t in v.group(1).split(',')]
            if len(vals) == 3 and max(abs(t) for t in vals) >= 1e7: far += 1
            elif len(vals) == 3:
                near += 1
                if len(nearex) < 4: nearex.append((vals, [ents[y].split('(')[0] for y in rev.get(x, [])][:2], [ents[z].split('(')[0] for y in rev.get(x, []) for z in rev.get(y, [])][:2]))
        info.update(mapped=types.get('MAPPED_ITEM', 0), cto=types.get('CARTESIAN_TRANSFORMATION_OPERATOR_3D', 0) + types.get('ITEM_DEFINED_TRANSFORMATION', 0), far_pts=far, near_pts=near, near_examples=nearex,
                    types={t: n for t, n in types.most_common(12)})
    print(json.dumps(info, default=str))
