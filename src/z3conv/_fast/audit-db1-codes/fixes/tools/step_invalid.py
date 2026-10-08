"""step_invalid.py [NPAR]: invalid solids of the deployed DB1 STEP outputs (versions: unversioned <= g, .h, .i) -> which parts, why
(OCC detail of the deployed solid) and which boolean operand causes it (mini IFC of the part from the same code's decoder IFC on this box
-> ifc2step6 -> OCC per variant). out: report/invalid.json"""
import json, os, sys, gzip, glob, subprocess, collections, concurrent.futures as cf
W = os.path.dirname(os.path.abspath(__file__)); os.chdir(W)
NPAR = int(sys.argv[1]) if len(sys.argv) > 1 else 8
PY84 = '/opt/conv/ifc84/bin/python'; PY = '/opt/conv/env/bin/python'
os.makedirs('inv', exist_ok=True); os.makedirs('report', exist_ok=True)
jobs = json.load(open('state/all_jobs.json'))
rows = []; per_ver = collections.Counter(); names = collections.defaultdict(collections.Counter)
for j in jobs:
    i = j['id']
    for suf in ('', '.h', '.i', '.j'):
        sp = f'det/{i}{suf}.step_parts.jsonl.gz'
        if not os.path.exists(sp):
            continue
        per_ver['models_' + (suf or 'u')] += 1
        for l in gzip.open(sp, 'rt'):
            x = json.loads(l)
            l4 = not x.get('solids') and 'L4' in (x.get('desc') or '')
            if (x.get('valid') or 0) < (x.get('solids') or 0) or l4:
                rows.append({'id': i, 'ver': suf or 'u', 'root': x.get('i'), 'gid': x.get('pid'), 'name': x.get('name'), 'cls': x.get('desc'),
                             'solids': x.get('solids'), 'valid': x.get('valid'), 'bbox': x.get('bbox'), 'volume': x.get('volume'),
                             'kind': 'L4-surface (no solid)' if l4 else 'invalid_solid'})
                per_ver['invalid_parts_' + (suf or 'u')] += 1; per_ver['invalid_solids_' + (suf or 'u')] += (x.get('solids') or 0) - (x.get('valid') or 0)
                names[suf or 'u'][(x.get('desc'), (x.get('name') or '').split(' [')[0][:40])] += 1


def deployed_detail(a):
    i, suf, roots = a
    o = f'inv/{i[:12]}{suf}.deployed.json'
    if not os.path.exists(o):
        subprocess.run([PY, 'occ_detail.py', f'out/{i}{suf}.stp', o, '--roots', ','.join(str(r) for r in roots)], capture_output=True, timeout=7200)
    return json.load(open(o)) if os.path.exists(o) else None


cur = [r for r in rows if r['ver'] in ('.h', '.i', '.j')]
grp = collections.defaultdict(list)
for r in cur:
    if r.get('solids'): grp[(r['id'], r['ver'])].append(r['root'])
with cf.ThreadPoolExecutor(min(NPAR, 6)) as ex:
    det = dict(zip(grp, ex.map(deployed_detail, [(i, s, rr) for (i, s), rr in grp.items()])))
for r in cur:
    d = det.get((r['id'], r['ver']))
    if d:
        for x in d['roots']:
            if x['root'] == r['root']:
                r['occ'] = [it for it in x['items'] if not it['valid']]


# map deployed product -> this box's decoder IFC of the same code (element order of the decoder IFC = census order)
def mapping(i, suf, kit):
    import ifcopenshell
    sp = f'det/{i}{suf}.src_parts.jsonl.gz'; ifc = f'dec/{kit}/{i}.ifc'
    if not (os.path.exists(sp) and os.path.exists(ifc)):
        return None
    dep = [json.loads(l) for l in gzip.open(sp, 'rt')]
    return dep


def mini(a):
    r, kit = a
    i = r['id']; tag = f"inv/{i[:12]}{r['ver']}_r{r['root']}"
    if os.path.exists(tag + '.json'):
        return json.load(open(tag + '.json'))
    res = {'id': i[:12], 'ver': r['ver'], 'root': r['root'], 'name': r['name']}
    try:
        # find my element: same position in the census order and same name
        dep = [json.loads(l) for l in gzip.open(f'det/{i}{r["ver"]}.src_parts.jsonl.gz', 'rt')]
        k = next((n for n, x in enumerate(dep) if x.get('gid') == r['gid']), None)
        q = subprocess.run([PY84, '-c', f'''
import ifcopenshell, json, sys
f = ifcopenshell.open("dec/{kit}/{i}.ifc")
els = [e for e in f.by_type("IfcProduct") if e.Representation is not None and not e.is_a("IfcSite")]
print(json.dumps([[e.GlobalId, e.Name] for e in els]))'''], capture_output=True, text=True, timeout=3600)
        mine = json.loads(q.stdout.strip().splitlines()[-1])
        dep_el = [x for x in dep if x.get('cls') not in ('IfcSite',)]
        same_seq = [x.get('name') for x in dep_el] == [m[1] for m in mine]
        res['order_names_equal'] = same_seq
        kk = next((n for n, x in enumerate(dep_el) if x.get('gid') == r['gid']), None)
        if kk is None or kk >= len(mine) or mine[kk][1] != r['name'] and (mine[kk][1] or '')[:60] != (r['name'] or '')[:60]:
            res['map'] = 'failed'; json.dump(res, open(tag + '.json', 'w')); return res
        g = mine[kk][0]; res['my_guid'] = g; res['map'] = 'order' if same_seq else 'order_name_checked'
        q = subprocess.run([PY84, 'mini_part.py', f'dec/{kit}/{i}.ifc', g, tag], capture_output=True, text=True, timeout=3600)
        info = json.loads(q.stdout.strip().splitlines()[-1]); res['part'] = {k_: v for k_, v in info.items() if k_ != 'variants'}
        res['variants'] = {}
        for nm, p in info['variants'].items():
            stp = p[:-4] + '.stp'
            subprocess.run([PY84, 'kits/common/ifc2step6.py', p, stp, '--mode', 'hybrid', '--prec', '2', '--threads', '1', '--no-surface-fallback'], capture_output=True, timeout=1800)
            if not os.path.exists(stp):
                res['variants'][nm] = 'no_step'; continue
            subprocess.run([PY, 'occ_detail.py', stp, stp + '.occ.json'], capture_output=True, timeout=1800)
            o = json.load(open(stp + '.occ.json')) if os.path.exists(stp + '.occ.json') else None
            if not o or not o['roots']:
                res['variants'][nm] = 'no_roots'; continue
            it = [x for rt in o['roots'] for x in rt['items']]
            res['variants'][nm] = {'solids': len(it), 'invalid': sum(1 for x in it if not x['valid']),
                                   'why': [{k_: v for k_, v in x.items() if k_ in ('status', 'free_edges', 'bop_faulty', 'faces_invalid', 'faces_tiny_lt_0.01mm2')} for x in it if not x['valid']][:2]}
    except Exception as e:
        res['error'] = f'{type(e).__name__}: {str(e)[:300]}'
    json.dump(res, open(tag + '.json', 'w'))
    return res


todo = []
seen = set()
for r in cur:
    kit = {'.i': 'i_audit', '.h': 'h_audit', '.j': 'j_audit'}[r['ver']]
    if not os.path.exists(f"dec/{kit}/{r['id']}.ifc"):
        continue
    key = (r['id'], r['ver'], r['name'])
    if key in seen and len(seen) > 400:
        continue
    seen.add(key)
    todo.append((r, kit))
with cf.ThreadPoolExecutor(NPAR) as ex:
    minis = list(ex.map(mini, todo))
cause = collections.Counter()
for m in minis:
    v = m.get('variants') or {}
    if not v: cause['not_tested:' + str(m.get('map') or m.get('error', ''))[:40]] += 1; continue
    inv = lambda n: (v.get(n) or {}).get('invalid') if isinstance(v.get(n), dict) else None
    if inv('none') == 0: cause['valid_in_isolation'] += 1
    elif inv('holes') == 0 and inv('cuts') != 0: cause['bolt_holes'] += 1
    elif inv('cuts') == 0 and inv('holes') != 0: cause['tekla_cuts'] += 1
    elif inv('holes') == 0 and inv('cuts') == 0: cause['either_holes_or_cuts'] += 1
    elif inv('all') == 0: cause['holes_and_cuts_together'] += 1
    else: cause['base_solid'] += 1
    singles = [n for n in v if n.startswith('op') and isinstance(v[n], dict) and v[n].get('invalid') == 0]
    m['single_operand_fix'] = singles
json.dump({'per_version': dict(per_ver), 'names': {k: [[list(a), b] for a, b in c.most_common(40)] for k, c in names.items()},
           'rows': rows, 'mini': minis, 'cause': dict(cause)}, open('report/invalid.json', 'w'), indent=1, default=str)
print(json.dumps({'per_version': dict(per_ver), 'cause': dict(cause)}, indent=1))
