"""nc1_check.py: the model folder's own DSTV NC1 files (Tekla NC export, BO block = drilled holes per piece) vs the holes the
builder cuts per part, deployed rule (jfix_audit2) vs P4 rule (jfixr_audit2). Parts matched by profile + length (+-2 mm).
out: report/nc1_check.json"""
import json, os, re, gzip, glob, collections, subprocess, boto3
W = os.path.dirname(os.path.abspath(__file__)); os.chdir(W)
PY84 = '/opt/conv/ifc84/bin/python'
s3 = boto3.client('s3')
jobs = {j['id']: j for j in json.load(open('state/all_jobs.json'))}
SIB = json.load(open('state/sib_index.json'))
out = {}


def parse_nc1(txt):
    lines = txt.replace('\r', '').split('\n')
    hdr = []; holes = []; blk = None
    for l in lines:
        if re.match(r'^[A-Z]{2}\s*$', l.strip()) and len(l.strip()) == 2:
            blk = l.strip(); continue
        if blk == 'ST':
            if l.strip().startswith('**'): continue
            hdr.append(l.strip())
        elif blk == 'BO':
            p = l.split()
            if len(p) >= 4:
                try: holes.append((p[0], float(re.sub('[a-z]', '', p[1])), float(re.sub('[a-z]', '', p[2])), float(re.sub('[a-z]', '', p[3]))))
                except ValueError: pass
    d = {'mark': hdr[3] if len(hdr) > 3 else None, 'qty': hdr[5] if len(hdr) > 5 else None, 'profile': hdr[6] if len(hdr) > 6 else None,
         'code': hdr[7] if len(hdr) > 7 else None, 'length': hdr[8] if len(hdr) > 8 else None, 'width': hdr[9] if len(hdr) > 9 else None,
         'holes': sum(1 for h in holes if h[3] > 0), 'diams': dict(collections.Counter(round(h[3], 1) for h in holes if h[3] > 0))}
    return d


def norm(p):
    return re.sub(r'[\s*xX]+', 'X', (p or '').upper()).strip()


for i, sib in SIB.items():
    ncs = [f for f in sib['files'] if f.lower().endswith('.nc1')]
    if not ncs: continue
    os.makedirs(f'nc1/{i[:12]}', exist_ok=True)
    N = []
    for f in ncs:
        dst = f'nc1/{i[:12]}/{f}'
        if not os.path.exists(dst): s3.download_file('bim-proprietary-data', sib['prefix'] + f, dst)
        N.append(parse_nc1(open(dst, 'rb').read().decode('latin-1')))
    res = {'nc1_files': len(N), 'nc1': N}
    for kit in ('jfix_audit2', 'jfixr_audit2'):
        ap = f'dec/{kit}/{i}.audit.json'
        if not os.path.exists(ap): continue
        A = json.load(open(ap)); pl = json.load(gzip.open(f'dec/{kit}/{i}.json.parts.json.gz', 'rt'))
        holes = collections.Counter(); hd = collections.defaultdict(collections.Counter)
        for b in A['bolts']:
            for p_ in b['hits']:
                holes[p_] += 1
        q = subprocess.run([PY84, '-c', f'''
import ifcopenshell, json
f = ifcopenshell.open("dec/{kit}/{i}.ifc"); out = {{}}
for e in f.by_type("IfcElement"):
    try:
        x = e.Representation.Representations[0].Items[0]
        while x.is_a("IfcBooleanResult"): x = x.FirstOperand
        sa = x.SweptArea
        if sa.is_a("IfcArbitraryClosedProfileDef"):
            P = [p.Coordinates for p in sa.OuterCurve.Points]; xs = [p[0] for p in P]; ys = [p[1] for p in P]
            d = sorted([max(xs) - min(xs), max(ys) - min(ys)], reverse=True)
            out[e.GlobalId] = ["plate", round(d[0], 1), round(d[1], 1)]
        else:
            out[e.GlobalId] = ["member", round(float(x.Depth), 1), None]
    except Exception: pass
print(json.dumps(out))'''], capture_output=True, text=True, timeout=3600)
        dims = json.loads(q.stdout.strip().splitlines()[-1])
        parts = [(r[0], r[1], dims.get(r[5])) for r in pl if r[3] == 'written' and r[4] not in ('bolt_group', 'holes_only_group')]
        cmp_ = []
        for n in N:
            try: Ln = float(n['length']); Wn = float(n['width'] or 0)
            except (TypeError, ValueError): continue
            def fits(p):
                if norm(p[1]) != norm(n['profile']) or not p[2]: return False
                if p[2][0] == 'plate': return abs(p[2][1] - max(Ln, Wn)) <= 2.0 and abs(p[2][2] - min(Ln, Wn)) <= 2.0
                return abs(p[2][1] - Ln) <= 2.0
            cand = [p for p in parts if fits(p)]
            cmp_.append({'mark': n['mark'], 'qty': n['qty'], 'profile': n['profile'], 'length': n['length'], 'width': n['width'], 'nc1_holes': n['holes'],
                         'nc1_diams': n['diams'], 'candidates': len(cand), 'builder_holes': sorted(holes.get(p[0], 0) for p in cand)})
        exact = sum(1 for c in cmp_ if c['candidates'] and all(h == c['nc1_holes'] for h in c['builder_holes']))
        matched = sum(1 for c in cmp_ if c['candidates'])
        res[kit] = {'matched_marks': matched, 'marks_all_instances_equal_nc1': exact,
                    'nc1_holes_matched': sum(c['nc1_holes'] for c in cmp_ if c['candidates']),
                    'builder_holes_first_instance': sum(c['builder_holes'][0] for c in cmp_ if c['candidates']), 'detail': cmp_}
    out[i] = res
json.dump(out, open('report/nc1_check.json', 'w'), indent=1)
for i, r in out.items():
    print(i[:12], r['nc1_files'], {k: {kk: v for kk, v in r[k].items() if kk != 'detail'} for k in ('jfix_audit2', 'jfixr_audit2') if k in r})
